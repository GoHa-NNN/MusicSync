"""adb_device_kit — Android ADB 设备通信与文件操作工具包。

从 MusicSync v1 提取的经过 bug 修复验证的底层模块，零外部依赖（仅 Python 标准库）。

版本: 1.0.0
许可: MIT
"""

__version__ = "1.0.0"

from .cancel_flag import CancelFlag
from .models import FileInfo, SkippedInfo, ScanResult, ActionResult
from .device import Device, DeviceError, CMD_TIMEOUT_SHORT, CMD_TIMEOUT_LIST, CMD_TIMEOUT_TRANSFER, QUICK_HASH_CHUNK
from .hash_utils import quick_hash, compute_local_hash
from .filter_utils import (
    AudioFilter,
    parse_musicignore,
    matches_any_rule,
    DEFAULT_AUDIO_EXTENSIONS,
)
from .executor_helpers import (
    transfer_with_verify,
    safe_delete_local,
    safe_delete_remote,
    format_size,
    HAS_SEND2TRASH,
)

__all__ = [
    # 版本
    "__version__",
    # 取消标志
    "CancelFlag",
    # 数据模型
    "FileInfo",
    "SkippedInfo",
    "ScanResult",
    "ActionResult",
    # ADB 设备层
    "Device",
    "DeviceError",
    "CMD_TIMEOUT_SHORT",
    "CMD_TIMEOUT_LIST",
    "CMD_TIMEOUT_TRANSFER",
    "QUICK_HASH_CHUNK",
    # 快速哈希
    "quick_hash",
    "compute_local_hash",
    # 文件过滤
    "AudioFilter",
    "parse_musicignore",
    "matches_any_rule",
    "DEFAULT_AUDIO_EXTENSIONS",
    # 传输与安全删除
    "transfer_with_verify",
    "safe_delete_local",
    "safe_delete_remote",
    "format_size",
    "HAS_SEND2TRASH",
]
