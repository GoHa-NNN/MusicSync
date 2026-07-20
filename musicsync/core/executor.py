"""同步执行器 — 文件传输 + 哈希校验 + 安全删除 + 重试。

对给定的差异列表逐项执行操作：
- copy / overwrite: shutil.copy2 → 哈希校验 → 失败重试 1 次
- delete: safe_delete_local（send2trash / 回退备份）

不直接操作数据库——返回 ``ActionResult`` 由调用方持久化。
"""

import os
import shutil
from typing import Optional

from musicsync.adb_device_kit.models import ActionResult
from musicsync.adb_device_kit.hash_utils import compute_local_hash
from musicsync.adb_device_kit.executor_helpers import (
    safe_delete_local,
)
from musicsync.adb_device_kit.cancel_flag import CancelFlag
from musicsync.core.models import DiffItem


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

_MAX_RETRIES = 1


def execute(
    diffs: list[DiffItem],
    source_root: str,
    dest_root: str,
    backup_dir: Optional[str] = None,
    cancel_flag: Optional[CancelFlag] = None,
) -> ActionResult:
    """执行同步操作列表。

    Args:
        diffs: 差异项列表（仅 .selected=True 的被执行）
        source_root: 源端根路径（拼接 source_root + relative_path → 源文件路径）
        dest_root: 目的端根路径（拼接 dest_root + relative_path → 目的文件路径）
        backup_dir: 删除备份目录（默认 ``"<dest_root>_backup"``）
        cancel_flag: 可选取消标志

    Returns:
        ``ActionResult`` — 成功/失败/跳过计数 + 失败详情 + 传输字节数
    """
    if backup_dir is None:
        backup_dir = dest_root.rstrip("/\\") + "_backup"

    result = ActionResult()

    for i, d in enumerate(diffs):
        if cancel_flag and cancel_flag.is_set():
            result.skip_count += sum(1 for x in diffs[i:] if x.selected)
            return result

        if not d.selected:
            result.skip_count += 1
            continue

        src_path = os.path.join(source_root, d.relative_path.replace("/", os.sep))
        dst_path = os.path.join(dest_root, d.relative_path.replace("/", os.sep))

        if d.operation in ("copy", "overwrite"):
            ok, err = _copy_with_verify(d, src_path, dst_path)
            if ok:
                result.success_count += 1
                result.total_bytes_transferred += d.source_size or 0
            else:
                result.failure_count += 1
                result.failures.append((d.relative_path, err))

        elif d.operation == "delete":
            ok, err = safe_delete_local(dst_path, d.relative_path, backup_dir)
            if ok:
                result.success_count += 1
            else:
                result.failure_count += 1
                result.failures.append((d.relative_path, err))

    return result


# ---------------------------------------------------------------------------
# 内部校验 copy + 重试
# ---------------------------------------------------------------------------

def _copy_with_verify(d: DiffItem, src_path: str, dst_path: str) -> tuple[bool, str]:
    """复制文件 + 哈希校验，失败重试最多 ``_MAX_RETRIES`` 次。"""
    if not os.path.exists(src_path):
        return (False, f"源文件不存在: {src_path}")

    file_size = d.source_size or os.path.getsize(src_path)

    # 确保目标目录存在
    dst_parent = os.path.dirname(dst_path)
    if dst_parent:
        os.makedirs(dst_parent, exist_ok=True)

    last_err = ""
    for attempt in range(_MAX_RETRIES + 1):
        # 复制
        try:
            shutil.copy2(src_path, dst_path)
        except OSError as e:
            last_err = f"复制失败: {e}"
            continue

        # 哈希校验
        src_hash = compute_local_hash(src_path, file_size)
        dst_hash = compute_local_hash(dst_path, file_size)
        if src_hash is None:
            last_err = f"无法读取源文件: {src_path}"
            continue
        if dst_hash is None:
            last_err = f"无法读取目标文件: {dst_path}"
            continue
        if src_hash != dst_hash:
            last_err = (
                f"传输后校验失败 "
                f"(源={src_hash[:8]}… 目标={dst_hash[:8]}…)"
            )
            continue

        return (True, "")

    return (False, last_err)
