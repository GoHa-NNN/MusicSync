"""传输校验与安全删除辅助函数。

从 MusicSync v1 Executor 类中提取的核心传输+校验+安全删除逻辑，
解耦为独立函数，不依赖任何项目特定的数据模型。

核心函数:
    - ``transfer_with_verify()`` — 传输文件并立即哈希校验，失败可重试
    - ``safe_delete_local()`` — 安全删除本地文件（send2trash 或备份）
    - ``safe_delete_remote()`` — 安全删除远程文件（先备份再删除）

Usage::

    from adb_device_kit import Device, transfer_with_verify

    device = Device()

    # PC → 手机: push + 校验
    ok, err = transfer_with_verify(
        transfer_fn=device.push,
        source_hash_fn=compute_local_hash,
        dest_hash_fn=lambda path, size: quick_hash(*device.read_head_tail(path), size),
        source_path="C:/song.flac",
        dest_path="//sdcard/Music/song.flac",
        file_size=26580279,
    )
    if not ok:
        print(f"传输失败: {err}")
"""

import os
import shutil
from typing import Optional, Callable

from .hash_utils import quick_hash, compute_local_hash

# ---------------------------------------------------------------------------
# send2trash 可选依赖
# ---------------------------------------------------------------------------

try:
    import send2trash

    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False


# ---------------------------------------------------------------------------
# 传输 + 校验
# ---------------------------------------------------------------------------

def transfer_with_verify(
    transfer_fn: Callable[[str, str], bool],
    source_hash_fn: Callable[[str, int], Optional[str]],
    dest_hash_fn: Callable[[str, int], Optional[str]],
    source_path: str,
    dest_path: str,
    file_size: int,
) -> tuple[bool, str]:
    """传输文件并在目标端校验完整性。

    流程:
        1. 计算源文件哈希
        2. 执行传输（调用 ``transfer_fn``）
        3. 计算目标文件哈希
        4. 比对确认一致

    Args:
        transfer_fn: 传输函数，签名为 ``(source_path, dest_path) -> bool``。
                     例如 ``device.push``（PC→手机）或 ``device.pull``（手机→PC）。
        source_hash_fn: 源端哈希计算函数，签名为 ``(path, size) -> str | None``。
                        例如 ``compute_local_hash``（PC 端文件）或自定义的手机端哈希函数。
        dest_hash_fn: 目标端哈希计算函数，签名同 ``source_hash_fn``。
        source_path: 源文件路径
        dest_path: 目标文件路径
        file_size: 文件大小（字节）

    Returns:
        ``(成功?, 错误信息)`` — 成功时错误信息为空字符串

    用法——PC → 手机 push + 校验::

        ok, err = transfer_with_verify(
            transfer_fn=device.push,
            source_hash_fn=compute_local_hash,
            dest_hash_fn=lambda path, size: quick_hash(*device.read_head_tail(path), size),
            source_path="C:/song.flac",
            dest_path="//sdcard/Music/song.flac",
            file_size=26580279,
        )

    用法——手机 → PC pull + 校验::

        ok, err = transfer_with_verify(
            transfer_fn=lambda src, dst: device.pull(src, dst),
            source_hash_fn=lambda path, size: quick_hash(*device.read_head_tail(path), size),
            dest_hash_fn=compute_local_hash,
            source_path="//sdcard/Music/song.flac",
            dest_path="C:/backup/song.flac",
            file_size=26580279,
        )
    """
    # 1. 计算源文件哈希
    src_hash = source_hash_fn(source_path, file_size)
    if src_hash is None:
        return (False, f"无法读取源文件: {source_path}")

    # 2. 执行传输
    if not transfer_fn(source_path, dest_path):
        return (False, f"传输失败: {source_path} → {dest_path}")

    # 3. 计算目标文件哈希
    dest_hash_val = dest_hash_fn(dest_path, file_size)
    if dest_hash_val is None:
        return (False, f"无法读取目标文件: {dest_path}")

    # 4. 比对
    if src_hash != dest_hash_val:
        return (
            False,
            f"传输后校验失败 (源={src_hash[:8]}… 目标={dest_hash_val[:8]}…)",
        )

    return (True, "")


# ---------------------------------------------------------------------------
# 安全删除（本地 / PC 端）
# ---------------------------------------------------------------------------

def safe_delete_local(local_path: str, relative_path: str, backup_dir: str) -> tuple[bool, str]:
    """安全删除 PC 端本地文件。

    优先使用 ``send2trash``（移入回收站，可恢复）；
    若 send2trash 不可用或失败，则移动文件到备份目录。

    Args:
        local_path: 要删除的本地文件绝对路径
        relative_path: 文件的相对路径（用于在备份目录中保留目录结构）
        backup_dir: 备份根目录（如 ``"C:/MusicSync_backup/"``）

    Returns:
        ``(成功?, 错误信息)``

    用法::

        ok, err = safe_delete_local(
            "C:/Music/old_song.flac",
            "VOCALOID/old_song.flac",
            "C:/MusicSync_backup/",
        )
        if ok:
            print("已移至回收站或备份目录")
    """
    if not os.path.exists(local_path):
        return (False, f"文件不存在: {local_path}")

    if HAS_SEND2TRASH:
        try:
            send2trash.send2trash(local_path)
            if not os.path.exists(local_path):
                return (True, "")
            # send2trash 执行完但文件仍在 → 回退到备份策略
        except Exception:
            pass

    # 回退：移到备份目录（保留相对路径结构）
    backup_path = os.path.join(
        backup_dir,
        relative_path.replace("/", os.sep),
    )
    backup_parent = os.path.dirname(backup_path)
    if backup_parent:
        os.makedirs(backup_parent, exist_ok=True)

    try:
        shutil.move(local_path, backup_path)
        return (True, "")
    except OSError as e:
        return (False, f"无法备份删除文件: {e}")


# ---------------------------------------------------------------------------
# 安全删除（远程 / 手机端）—— 先备份再删除
# ---------------------------------------------------------------------------

def safe_delete_remote(
    device: object,  # Device 实例
    remote_path: str,
    relative_path: str,
    backup_dir: str,
    cancel_flag: Optional[object] = None,
) -> tuple[bool, str]:
    """安全删除手机端文件：先拉取备份到 PC → 校验备份完整性 → 再执行远程删除。

    **为什么需要备份**: ADB 没有回收站概念，``rm`` 不可逆。
    先备份到 PC 确保即使后续需要恢复数据也有副本。

    流程:
        1. 创建备份目录（保留相对路径结构）
        2. 获取远程文件元数据（size）
        3. 拉取文件到 PC 备份目录
        4. 比对源端和目标端哈希确认备份完整
        5. 删除手机端文件 + 验证已删除

    Args:
        device: ``Device`` 实例，需有 ``stat``、``pull``、``read_head_tail``、``delete`` 方法
        remote_path: 手机端文件路径，如 ``"//sdcard/Music/song.flac"``
        relative_path: 相对路径，用于备份目录结构
        backup_dir: PC 端备份根目录
        cancel_flag: 可选的 ``CancelFlag`` 实例

    Returns:
        ``(成功?, 错误信息)``

    用法::

        from adb_device_kit import Device, safe_delete_remote

        device = Device()
        ok, err = safe_delete_remote(
            device=device,
            remote_path="//sdcard/Music/old.flac",
            relative_path="VOCALOID/old.flac",
            backup_dir="C:/MusicSync_backup/",
        )
        if not ok:
            print(f"删除失败: {err}")
    """
    # 1. 准备备份路径（保留相对路径结构）
    backup_path = os.path.join(
        backup_dir,
        relative_path.replace("/", os.sep),
    )
    backup_parent = os.path.dirname(backup_path)
    if backup_parent:
        os.makedirs(backup_parent, exist_ok=True)

    # 2. 获取源文件信息
    info = device.stat(remote_path)
    if info is None:
        return (False, f"手机端文件不存在或无法访问: {remote_path}")
    file_size = info["size"]

    # 3. 备份：拉取到 PC
    if not device.pull(remote_path, backup_path, cancel_flag):
        return (False, f"备份拉取失败: {remote_path} → {backup_path}")

    # 4. 验证备份完整性
    dst_hash = compute_local_hash(backup_path, file_size)
    if dst_hash is None:
        return (False, f"无法读取备份文件: {backup_path}")

    head, tail = device.read_head_tail(remote_path, cancel_flag=cancel_flag)
    src_hash = quick_hash(head, tail, file_size)

    if dst_hash != src_hash:
        return (
            False,
            f"备份校验失败 (源={src_hash[:8]}… 备份={dst_hash[:8]}…)",
        )

    # 5. 删除手机端文件
    if not device.delete(remote_path, cancel_flag):
        return (False, f"手机端删除失败: {remote_path}")

    return (True, "")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def format_size(size_bytes: int) -> str:
    """格式化文件大小为人类可读格式。

    Args:
        size_bytes: 字节数

    Returns:
        格式化字符串，如 ``"1.5MB"`` / ``"420KB"`` / ``"128B"``

    用法::

        format_size(0)       # "0B"
        format_size(500)     # "500B"
        format_size(1500)    # "1KB"
        format_size(26580279)  # "25.3MB"
    """
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f}GB"
