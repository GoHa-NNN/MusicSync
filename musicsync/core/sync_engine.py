"""同步引擎 — scan + compare 纯函数管道。

PC→PC 扫描用 ``os.walk`` + ``AudioFilter``。
比对阶段为纯数据操作，不涉及文件 I/O
（哈希计算委托给 ``compute_local_hash()``，仅对 size 不匹配的文件对调用）。
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional, Callable, TYPE_CHECKING

from musicsync.adb_device_kit.models import FileInfo, SkippedInfo
from musicsync.adb_device_kit.filter_utils import AudioFilter
from musicsync.adb_device_kit.hash_utils import compute_local_hash
from musicsync.adb_device_kit.cancel_flag import CancelFlag
from musicsync.adb_device_kit.device import DeviceError
from musicsync.core.models import DiffItem

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from musicsync.adb_device_kit.device import Device


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def scan(
    root_path: str,
    extensions: list[str],
    musicignore_rules: Optional[list[str]] = None,
    device: "Optional[Device]" = None,
    cancel_flag: Optional[CancelFlag] = None,
    progress_callback: Optional[Callable] = None,
) -> tuple[list[FileInfo], SkippedInfo]:
    """扫描目录下的音频文件。

    ``device=None`` 时使用 ``os.walk``（PC 本地），
    ``device`` 为非 None 时委托其 ``list_files()`` / ``stat()``（Phone ADB）。

    Args:
        root_path: 根目录路径
        extensions: 音频扩展名白名单（小写，不含点）
        musicignore_rules: ``parse_musicignore()`` 产出的规则列表
        device: ``None`` 表示 PC，``Device`` 实例表示 Phone
        cancel_flag: 可选取消标志
        progress_callback: 可选进度回调，签名 ``callback(stage, phase, current, total, detail)``

    Returns:
        ``(files, skipped)`` — 经过滤的 FileInfo 列表，以及跳过文件统计
    """
    if cancel_flag and cancel_flag.is_set():
        return [], SkippedInfo()

    f = AudioFilter(extensions=extensions)
    if musicignore_rules:
        f.musicignore_rules = musicignore_rules

    # 规范化根路径（去除末尾分隔符）
    root = os.path.normpath(root_path)

    if device is not None:
        try:
            result = _scan_phone(device, root_path, f, cancel_flag, progress_callback)
        except DeviceError as e:
            _log.error("Phone 扫描失败: %s", e)
            result = []
    else:
        result = _scan_pc(root, f, cancel_flag, progress_callback)

    return result, f.get_skipped_summary()


def _scan_pc(
    root: str,
    f: AudioFilter,
    cancel_flag: Optional[CancelFlag],
    progress_callback: Optional[Callable] = None,
) -> list[FileInfo]:
    """PC 本地扫描：os.walk + AudioFilter.filter()。"""
    # 收集所有文件路径
    all_files: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if cancel_flag and cancel_flag.is_set():
            return []
        for name in filenames:
            all_files.append(os.path.join(dirpath, name))

    # 批量过滤（自动收集 SkippedInfo）
    kept, _skipped = f.filter(all_files, side="source")

    result: list[FileInfo] = []
    total = len(kept)
    for idx, full_path in enumerate(kept):
        if cancel_flag and cancel_flag.is_set():
            return []
        rel = os.path.relpath(full_path, root).replace("\\", "/")
        stat = os.stat(full_path)
        result.append(FileInfo(
            path=full_path,
            relative_path=rel,
            size=stat.st_size,
            modified=datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        ))
        # 每 50 个文件报告一次进度
        if progress_callback and (idx + 1) % 50 == 0:
            progress_callback("scan", "source", idx + 1, total, "")
        if progress_callback:
            progress_callback("scan", "source", idx + 1, total, rel)

    if progress_callback:
        progress_callback("scan", "source", total, total, "")
    return result


def _scan_phone(
    device: "Device",
    root_path: str,
    f: AudioFilter,
    cancel_flag: Optional[CancelFlag],
    progress_callback: Optional[Callable] = None,
) -> list[FileInfo]:
    """Phone ADB 扫描：一次 ``find -printf`` 获取路径+大小（无 N+1 查询）。

    与旧版（list_files + 逐文件 stat，每次 62ms ADB 往返）相比，
    347 文件从 ~22s 降为 ~0.2s，约 100× 提升。
    """
    entries = device.list_files_with_sizes(root_path, cancel_flag=cancel_flag)
    result: list[FileInfo] = []
    total = len(entries)
    for idx, (full_path, file_size) in enumerate(entries):
        if cancel_flag and cancel_flag.is_set():
            return []
        if not f.should_include(full_path):
            continue
        # 关键：去掉 root_path 前缀保留相对路径
        root_norm = root_path.rstrip("/").lstrip("/")  # "sdcard/Music"
        fp = full_path.replace("\\", "/").lstrip("/")   # "sdcard/Music/song.flac"
        pos = fp.find(root_norm)
        if pos >= 0:
            rel = fp[pos + len(root_norm):].lstrip("/")
        else:
            rel = fp  # fallback
        result.append(FileInfo(
            path=full_path,
            relative_path=rel,
            size=file_size,
            modified=None,  # Phone 端不读 mtime（比对不依赖修改时间）
        ))
        # 每 50 个文件报告一次进度
        if progress_callback and (idx + 1) % 50 == 0:
            progress_callback("scan", "source", idx + 1, total, "")
        if progress_callback:
            progress_callback("scan", "source", idx + 1, total, rel)

    if progress_callback:
        progress_callback("scan", "source", total, total, "")
    return result


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------

def compare(
    source_files: list[FileInfo],
    dest_files: list[FileInfo],
    cancel_flag: Optional[CancelFlag] = None,
) -> list[DiffItem]:
    """比对两端文件列表，返回差异项（不含 synced）。

    匹配键为 ``relative_path``。策略:

    - 两端都有 + 大小相同 → synced（跳过）
    - 两端都有 + 大小不同 → 哈希确认 → 哈希不同 = updated_in_dest
    - 仅在源端 → new_in_dest
    - 仅在目的端 → only_in_dest

    对已预先填充 ``hash`` 的 FileInfo 直接使用，否则在需要时调用
    ``compute_local_hash()`` 计算。

    Args:
        source_files: 源端文件列表
        dest_files: 目的端文件列表
        cancel_flag: 可选取消标志，已设置时立即返回空列表

    Returns:
        差异项列表（diff_type 为 new_in_dest / updated_in_dest / only_in_dest）
    """
    if cancel_flag and cancel_flag.is_set():
        return []

    src_index: dict[str, FileInfo] = {f.relative_path: f for f in source_files}
    dst_index: dict[str, FileInfo] = {f.relative_path: f for f in dest_files}
    all_paths = set(src_index) | set(dst_index)

    diffs: list[DiffItem] = []

    for rel_path in sorted(all_paths):
        if cancel_flag and cancel_flag.is_set():
            return []

        src_file = src_index.get(rel_path)
        dst_file = dst_index.get(rel_path)

        if src_file and dst_file:
            if src_file.size == dst_file.size:
                continue  # synced

            # 大小不同 → 哈希确认
            src_hash = _ensure_hash(src_file)
            dst_hash = _ensure_hash(dst_file)
            if src_hash and dst_hash and src_hash == dst_hash:
                continue  # 内容相同，视为 synced

            diffs.append(DiffItem(
                relative_path=rel_path,
                diff_type="updated_in_dest",
                operation="overwrite",
                direction="source → dest",
                source_size=src_file.size,
                dest_size=dst_file.size,
            ))

        elif src_file and not dst_file:
            diffs.append(DiffItem(
                relative_path=rel_path,
                diff_type="new_in_dest",
                operation="copy",
                direction="source → dest",
                source_size=src_file.size,
                dest_size=None,
            ))

        elif not src_file and dst_file:
            diffs.append(DiffItem(
                relative_path=rel_path,
                diff_type="only_in_dest",
                operation="delete",
                direction="dest",
                source_size=None,
                dest_size=dst_file.size,
            ))

    return diffs


# ---------------------------------------------------------------------------
# 内部哈希辅助
# ---------------------------------------------------------------------------

def _ensure_hash(f: FileInfo) -> Optional[str]:
    """确保 FileInfo 有哈希值——已有则复用，否则计算。"""
    if f.hash is not None:
        return f.hash
    if f.path and f.size is not None:
        return compute_local_hash(f.path, f.size)
    return None
