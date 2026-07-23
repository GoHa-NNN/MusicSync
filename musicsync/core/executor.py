"""同步执行器 — 文件传输 + 哈希校验 + 安全删除 + 重试。

对给定的差异列表逐项执行操作：
- copy / overwrite: transfer_fn → 哈希校验 → 失败重试 1 次
- delete: PC 端 safe_delete_local / Phone 端 safe_delete_remote

不直接操作数据库——返回 ``ActionResult`` 由调用方持久化。

设备组合分发：
- source_device=None + dest_device=None → PC→PC（shutil.copy2）
- source_device=None + dest_device=<Device> → PC→Phone（device.push）
- source_device=<Device> + dest_device=None → Phone→PC（device.pull）
"""

import os
import shutil
import sys
from typing import Optional, Callable, TYPE_CHECKING

from musicsync.adb_device_kit.models import ActionResult
from musicsync.adb_device_kit.hash_utils import compute_local_hash, quick_hash
from musicsync.adb_device_kit.executor_helpers import (
    safe_delete_local,
    safe_delete_remote,
    transfer_with_verify,
)
from musicsync.adb_device_kit.cancel_flag import CancelFlag, CancelledError
from musicsync.core.models import DiffItem

if TYPE_CHECKING:
    from musicsync.adb_device_kit.device import Device


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

_MAX_RETRIES = 1


def execute(
    diffs: list[DiffItem],
    source_root: str,
    dest_root: str,
    source_device: "Optional[Device]" = None,
    dest_device: "Optional[Device]" = None,
    backup_dir: Optional[str] = None,
    cancel_flag: Optional[CancelFlag] = None,
    progress_callback: Optional[Callable] = None,
) -> ActionResult:
    """执行同步操作列表。

    Args:
        diffs: 差异项列表（仅 .selected=True 的被执"）
        source_root: 源端根路径（拼接 source_root + relative_path → 源文件路径）
        dest_root: 目的端根路径（拼接 dest_root + relative_path → 目的文件路径）
        source_device: ``None`` 表示源端为 PC，``Device`` 实例表示 Phone
        dest_device: ``None`` 表示目的端为 PC，``Device`` 实例表示 Phone
        backup_dir: 删除备份目录
            - Phone 端删除：默认 ``"<app_dir>/backups/<dest_dir_name>_phone_backup"``
            - PC 端删除：默认 ``"<dest_root>_backup"``
        cancel_flag: 可选取消标志
        progress_callback: 可选进度回调，签名 ``callback(stage, phase, current, total, detail)``

    Returns:
        ``ActionResult`` — 成功/失败/跳过计数 + 失败详情 + 传输字节数
    """
    # ── 设备分发：选择传输/哈希/删除函数 ──
    is_source_phone = source_device is not None
    is_dest_phone = dest_device is not None

    if backup_dir is None:
        if is_dest_phone:
            # Phone 端删除备份存放在程序运行目录下，保持绿色不污染用户目录
            if getattr(sys, "frozen", False):
                app_dir = os.path.dirname(sys.executable)
            else:
                # executor.py 位于 musicsync/core/，项目根在往上 3 级
                app_dir = os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.abspath(__file__))
                    )
                )
            dest_dir_name = os.path.basename(dest_root.rstrip("/\\"))
            backup_dir = os.path.join(
                app_dir, "backups", f"{dest_dir_name}_phone_backup"
            )
        else:
            backup_dir = dest_root.rstrip("/\\") + "_backup"

    if is_source_phone and is_dest_phone:
        # 本增量明确不做 Phone→Phone
        raise NotImplementedError("Phone→Phone 不在当前版本支持范围")

    # - transfer_fn: (src_path, dst_path) -> bool
    # - source_hash_fn / dest_hash_fn: (path, size) -> str | None
    # - delete_fn: (path, relative_path, backup_dir) -> (bool, str)

    if is_source_phone:  # Phone→PC
        # 手机端用 read_head_tail 做 quick_hash
        source_hash_fn = _make_phone_hash(source_device)
        dest_hash_fn = compute_local_hash

        def transfer_fn(s: str, d: str) -> bool:
            os.makedirs(os.path.dirname(d), exist_ok=True)
            return source_device.pull(s, d, cancel_flag=cancel_flag)

        # Phone→PC 删除 PC 端文件
        delete_fn = safe_delete_local

    elif is_dest_phone:  # PC→Phone
        source_hash_fn = compute_local_hash
        dest_hash_fn = _make_phone_hash(dest_device)

        def transfer_fn(s: str, d: str) -> bool:
            return dest_device.push(s, d, cancel_flag=cancel_flag)

        # PC→Phone 删除手机端文件
        def delete_fn(
            path: str, rel: str, backup: str
        ) -> tuple[bool, str]:
            return safe_delete_remote(
                dest_device, path, rel, backup, cancel_flag=cancel_flag,
            )

    else:  # PC→PC
        source_hash_fn = compute_local_hash
        dest_hash_fn = compute_local_hash

        def transfer_fn(s: str, d: str) -> bool:
            try:
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copy2(s, d)
                return True
            except OSError:
                return False

        delete_fn = safe_delete_local

    # ── 逐项执行 ──
    result = ActionResult()

    selected_diffs = [d for d in diffs if d.selected]
    total_selected = len(selected_diffs)

    for i, d in enumerate(diffs):
        if cancel_flag and cancel_flag.is_set():
            result.skip_count += sum(1 for x in diffs[i:] if x.selected)
            if progress_callback:
                progress_callback("execute", "done", i, total_selected, "")
            return result

        if not d.selected:
            result.skip_count += 1
            continue

        rel = d.relative_path.replace("\\", "/")

        if progress_callback:
            detail = rel
            phase = "transferring" if d.operation != "delete" else "deleting"
            progress_callback("execute", phase, result.success_count, total_selected, detail)
        src_path = os.path.join(source_root, rel.replace("/", os.sep))
        # Phone 端路径用正斜杠，不拼 os.sep
        phone_src = _phone_path(source_root, rel) if is_source_phone else src_path
        dst_path = os.path.join(dest_root, rel.replace("/", os.sep))
        phone_dst = _phone_path(dest_root, rel) if is_dest_phone else dst_path

        if d.operation in ("copy", "overwrite"):
            file_size = d.source_size or (
                os.path.getsize(src_path)
                if not is_source_phone and os.path.exists(src_path)
                else 0
            )

            _src = phone_src if is_source_phone else src_path
            _dst = phone_dst if is_dest_phone else dst_path

            ok, err = _transfer_with_retry(
                transfer_fn,
                source_hash_fn,
                dest_hash_fn,
                _src,
                _dst,
                file_size,
            )
            if ok:
                result.success_count += 1
                result.total_bytes_transferred += d.source_size or 0
            else:
                result.failure_count += 1
                result.failures.append((d.relative_path, err))

        elif d.operation == "delete":
            ok, err = delete_fn(
                phone_dst if is_dest_phone else dst_path,
                d.relative_path,
                backup_dir,
            )
            if ok:
                result.success_count += 1
            else:
                result.failure_count += 1
                result.failures.append((d.relative_path, err))

    if progress_callback:
        progress_callback("execute", "done", total_selected, total_selected, "")

    return result


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

def _transfer_with_retry(
    transfer_fn,
    source_hash_fn,
    dest_hash_fn,
    source_path: str,
    dest_path: str,
    file_size: int,
) -> tuple[bool, str]:
    """调用 transfer_with_verify，失败重试最多 ``_MAX_RETRIES`` 次。"""
    err = ""
    for _attempt in range(_MAX_RETRIES + 1):
        ok, err = transfer_with_verify(
            transfer_fn=transfer_fn,
            source_hash_fn=source_hash_fn,
            dest_hash_fn=dest_hash_fn,
            source_path=source_path,
            dest_path=dest_path,
            file_size=file_size,
        )
        if ok:
            return (True, "")
    return (False, err)


def _make_phone_hash(device: "Device"):
    """构造 Phone 端哈希函数：``quick_hash(*device.read_head_tail(path), size)``。"""
    def phone_hash(path: str, size: int) -> Optional[str]:
        head, tail = device.read_head_tail(path)
        if head is None and tail is None:
            return None
        return quick_hash(head, tail, size)
    return phone_hash


def _phone_path(root: str, relative_path: str) -> str:
    """拼接 Phone 端文件路径（正斜杠，不转 ``\\``）。"""
    root = root.rstrip("/")
    return root + "/" + relative_path.replace("\\", "/")
