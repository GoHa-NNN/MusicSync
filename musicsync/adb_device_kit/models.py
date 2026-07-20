"""共享数据模型。

纯数据结构（dataclass），无业务逻辑、无 I/O 依赖。
供本包内其他模块使用，也可被外部调用方直接导入。
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 单个文件元数据快照
# ---------------------------------------------------------------------------

@dataclass
class FileInfo:
    """单个文件的元数据快照。

    属性:
        path (str): 文件完整路径（PC 端为本地路径，手机端为 ADB 路径如 ``//sdcard/...``）
        relative_path (str): 相对于根目录的路径，用于跨设备文件匹配
        size (int | None): 文件大小（字节），``None`` 表示文件不存在
        modified (str | None): ISO 8601 格式修改时间（如 ``"2026-07-17T12:34:56+00:00"``），``None`` 表示不可用
        hash (str | None): 快速哈希值（按需计算），``None`` 表示未计算

    用法::

        f = FileInfo(
            path="//sdcard/Music/song.flac",
            relative_path="VOCALOID/song.flac",
            size=26580279,
            modified="2026-01-15T08:30:00+00:00",
        )
    """

    path: str
    relative_path: str
    size: Optional[int] = None
    modified: Optional[str] = None
    hash: Optional[str] = None


# ---------------------------------------------------------------------------
# 跳过文件统计
# ---------------------------------------------------------------------------

@dataclass
class SkippedInfo:
    """扫描时被跳过的文件统计信息。

    属性:
        total (int): 跳过文件总数
        by_extension (dict[str, int]): 按扩展名分组的计数，如 ``{".jpg": 77, ".tmp": 3}``
        by_side (dict[str, int]): 按设备端分组的计数，如 ``{"source": 2, "dest": 80}``
        file_list (list[str]): 被跳过的文件完整路径列表

    用法::

        summary = audio_filter.get_skipped_summary()
        print(f"跳过了 {summary.total} 个文件")
        print(f"  按扩展名: {summary.by_extension}")
        print(f"  按设备: {summary.by_side}")
    """

    total: int = 0
    by_extension: dict[str, int] = field(default_factory=dict)
    by_side: dict[str, int] = field(default_factory=dict)
    file_list: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 阶段产出
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    """扫描阶段产出。

    属性:
        source_files (list[FileInfo]): 源端文件列表
        dest_files (list[FileInfo]): 目的端文件列表
    """

    source_files: list[FileInfo] = field(default_factory=list)
    dest_files: list[FileInfo] = field(default_factory=list)


@dataclass
class ActionResult:
    """执行阶段产出（传输 / 删除等操作的汇总结果）。

    属性:
        success_count (int): 成功数
        failure_count (int): 失败数
        skip_count (int): 跳过数（用户取消等原因）
        failures (list[tuple[str, str]]): 失败详情，每项为 ``(文件路径, 错误信息)``
        total_bytes_transferred (int): 总传输字节数（删除操作不计入）
    """

    success_count: int = 0
    failure_count: int = 0
    skip_count: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    total_bytes_transferred: int = 0
