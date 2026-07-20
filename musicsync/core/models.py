"""核心数据模型。

新增 DiffItem（差异项），其余已有模型从 adb_device_kit 复用。
"""

from dataclasses import dataclass
from typing import Optional

# 复用 adb_device_kit 的已有模型
from musicsync.adb_device_kit.models import (
    FileInfo,
    ActionResult,
    ScanResult,
)


@dataclass
class DiffItem:
    """单个差异项——比对阶段产出，供执行阶段消费。

    属性:
        relative_path: 文件相对路径（唯一键）
        diff_type: ``"new_in_dest"`` / ``"updated_in_dest"`` / ``"only_in_dest"``
        operation: ``"copy"`` / ``"overwrite"`` / ``"delete"``（与 DB 约束一致）
        direction: 操作方向描述
        source_size: 源端文件大小（字节）
        dest_size: 目的端文件大小（字节）
        selected: 是否勾选（默认 True）
    """

    relative_path: str
    diff_type: str       # "new_in_dest" | "updated_in_dest" | "only_in_dest"
    operation: str       # "copy" | "overwrite" | "delete"（与 DB CHECK 一致）
    direction: str = ""
    source_size: Optional[int] = None
    dest_size: Optional[int] = None
    selected: bool = True
