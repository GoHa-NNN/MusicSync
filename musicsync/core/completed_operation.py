"""操作完成事件 — 方向标签构造 + DB 记录参数工厂。

将 CLI 和 GUI 中散落的 direction 标签构建逻辑收敛到一个 deep module，
使 record_operation() 调用路径统一为单一路径。
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CompletedOperation:
    """一次成功的同步操作产生的领域事件。

    封装 ``DiffItem`` + 设备标签 → 直接提供 ``database.record_operation()``
    所需的参数字典，以及面向 UI 展示的方向标签。

    Args:
        operation: ``"copy"`` / ``"overwrite"`` / ``"delete"``
        relative_path: 文件相对路径
        source_size: 源端文件大小（字节）
        dest_size: 目的端文件大小（字节）
        src_label: 源端设备标签（``"PC"`` / ``"Phone"``）
        dst_label: 目的端设备标签（``"PC"`` / ``"Phone"``）
    """

    operation: str
    relative_path: str
    source_size: Optional[int] = None
    dest_size: Optional[int] = None
    src_label: str = "PC"
    dst_label: str = "PC"

    # ------------------------------------------------------------------
    # 方向标签
    # ------------------------------------------------------------------

    @property
    def direction_for_db(self) -> str:
        """DB 存储用的方向标签（v2 格式）。

        copy/overwrite: ``"PC → Phone"``
        delete:         ``"Phone"``（仅目的端设备标签）
        """
        if self.operation == "delete":
            return self.dst_label
        return f"{self.src_label} → {self.dst_label}"

    # ------------------------------------------------------------------
    # DB 写入参数
    # ------------------------------------------------------------------

    def to_record_params(self) -> dict:
        """返回给 ``database.record_operation(conn, **params)`` 的 kwargs。"""
        return {
            "action_type": self.operation,
            "direction": self.direction_for_db,
            "relative_path": self.relative_path,
            "file_size": self.source_size or self.dest_size or 0,
            "dest_size": self.dest_size if self.operation == "overwrite" else None,
        }

    @classmethod
    def from_diff_item(cls, diff, src_label: str, dst_label: str) -> "CompletedOperation":
        """从 DiffItem 构造 CompletedOperation。

        此工厂方法统一了 GUI 和 CLI 中的方向标签构造逻辑，
        消除了两个表现层各自拼接 direction 字符串的代码重复。
        """
        return cls(
            operation=diff.operation,
            relative_path=diff.relative_path,
            source_size=diff.source_size,
            dest_size=diff.dest_size,
            src_label=src_label,
            dst_label=dst_label,
        )


# ---------------------------------------------------------------------------
# DirectionFormatter — 方向字符串解析与格式化
# ---------------------------------------------------------------------------

class DirectionFormatter:
    """解析和格式化方向标签。

    处理 v2 格式（含设备标签，如 ``"PC → Phone"``）和
    v1 格式（泛化标签，如 ``"source → dest"``），
    确保历史数据正常显示。
    """

    V1_GENERIC_SRC = {"source", "源"}
    V1_GENERIC_DST = {"dest", "目的"}
    DELETE_V1 = {"dest"}

    @classmethod
    def parse_display(cls, action_type: str, direction: str) -> str:
        """从 action_type + direction 构造成展示文本。

        Args:
            action_type: ``"copy"`` / ``"overwrite"`` / ``"delete"``
            direction: 数据库中存储的方向字符串

        Returns:
            展示用描述，如 ``"复制 [PC] → [Phone]"``
        """
        action_map = {
            "copy": "复制",
            "overwrite": "覆盖",
            "delete": "删除",
        }
        act = action_map.get(action_type, action_type)
        return cls._format_action(act, direction)

    @staticmethod
    def _format_action(action: str, direction: str) -> str:
        """根据 direction 格式生成展示文本。"""
        arrow = "→"
        if arrow in direction:
            parts = [p.strip() for p in direction.split(arrow) if p.strip()]
            if len(parts) == 2 and parts[0] not in DirectionFormatter.V1_GENERIC_SRC:
                return f"{action} [{parts[0]}] → [{parts[1]}]"
            # v1 兼容：泛化标签回退到 [PC]
            return f"{action} [PC] → [PC]"
        else:
            # delete-only 方向
            if direction in ("PC", "Phone"):
                return f"{action} in [{direction}]"
            # v1 兼容
            return f"{action}"
