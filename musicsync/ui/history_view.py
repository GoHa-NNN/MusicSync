"""操作历史面板 — 从 operation_history 表按时间倒序展示。

列: 时间 | 操作(含方向) | 文件名 | 大小
"""

import sqlite3
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt

from musicsync.adb_device_kit.executor_helpers import format_size
from musicsync.store.database import list_operations


def _action_display(action_type: str, direction: str) -> str:
    """操作类型 + 方向合并为一行展示。

    direction 格式（v2，含设备标签）:
      - copy/overwrite: ``"PC → Phone"`` / ``"Phone → PC"`` / ``"PC → PC"``
      - delete:         ``"PC"`` / ``"Phone"``

    v1 兼容: ``"source → dest"`` / ``"dest"`` — 回退为 [PC]→[PC] / 删除 in [PC]
    """
    action_map = {"copy": "复制", "overwrite": "覆盖", "delete": "删除"}
    act = action_map.get(action_type, action_type)

    # 从 direction 解析设备标签
    if "→" in direction:
        parts = [p.strip() for p in direction.split("→")]
        if len(parts) == 2:
            src, dst = parts
            # v2: PC/Phone → PC/Phone
            if src in ("PC", "Phone") and dst in ("PC", "Phone"):
                return f"{act} [{src}] → [{dst}]"
        # v1 兼容: "source → dest"
        return f"{act} [PC] → [PC]"
    else:
        # delete: v2 = "PC" / "Phone", v1 = "dest"
        if direction in ("PC", "Phone"):
            return f"{act} in [{direction}]"
        # v1 兼容: "dest"
        return f"{act} in [PC]"


class HistoryView(QWidget):
    """操作历史表格。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["时间", "操作", "文件名", "大小"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        self._table.setColumnWidth(0, 130)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        self._table.setColumnWidth(1, 130)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        self._table.setColumnWidth(2, 200)
        hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        self._table.setColumnWidth(3, 80)

        root.addWidget(self._table)

    def refresh(self, conn: sqlite3.Connection) -> None:
        records = list_operations(conn, limit=50)
        self._table.setRowCount(len(records))

        for row, r in enumerate(records):
            # 时间
            ts = r["timestamp"]
            try:
                dt = datetime.fromisoformat(ts)
                # 转本地时区显示（存储为 UTC）
                if dt.tzinfo is not None:
                    dt_local = dt.astimezone()
                else:
                    dt_local = dt
                ts_display = dt_local.strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts_display = ts[:16]
            ts_item = QTableWidgetItem(ts_display)
            ts_item.setFlags(ts_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 0, ts_item)

            # 操作 + 方向
            action_text = _action_display(r["action_type"], r["direction"])
            action_item = QTableWidgetItem(action_text)
            action_item.setFlags(action_item.flags() & ~Qt.ItemIsEditable)
            action_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, 1, action_item)

            # 文件名
            path_item = QTableWidgetItem(r["relative_path"])
            path_item.setToolTip(r["relative_path"])
            path_item.setFlags(path_item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(row, 2, path_item)

            # 大小
            size_text = format_size(r["file_size"])
            size_item = QTableWidgetItem(size_text)
            size_item.setFlags(size_item.flags() & ~Qt.ItemIsEditable)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row, 3, size_item)

            self._table.setRowHeight(row, 24)
