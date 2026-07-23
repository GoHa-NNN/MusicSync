"""差异列表 — 按操作类型分标签页展示差异项。

每行：复选框 + 相对路径 + 源端(设备+大小) + 目的端(设备+大小) + 方向(设备→设备)

弃用 emoji（Qt 渲染兼容性差），改用纯文本: [PC] / [Phone]
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from musicsync.adb_device_kit.executor_helpers import format_size
from musicsync.core.models import DiffItem


DEVICE_PC    = "[PC]"
DEVICE_PHONE = "[Phone]"

TAB_CONFIG = [
    ("copy",      "复制到目的"),
    ("overwrite", "覆盖目的"),
    ("delete",    "从目的删除"),
]


def format_device_size(device_label: str, size) -> str:
    if size is None:
        return f"{device_label} —"
    return f"{device_label} {format_size(size)}"


class DiffView(QWidget):
    """差异列表三标签页组件。"""

    selection_changed = Signal(int, int, object)
    # NOTE: 第三个参数用 object 而非 int，因为 PySide6 将 int 映射为 C++ signed 32-bit
    # (上限 ~2.1GB)。文件大小合计（selected_total_bytes）可能超过此值，导致 shiboken
    # overflow → Slot 签名损坏 → AttributeError。object 类型让 Python 原生 int
    # 原样传递，下游 format_size() 对 Python int 类型无感。

    def __init__(self, parent=None):
        super().__init__(parent)
        self._diffs: list[DiffItem] = []
        self._src_label = DEVICE_PC
        self._dst_label = DEVICE_PC
        self._diff_by_operation: dict[str, list[DiffItem]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._tab_widget = QTabWidget()
        self._table_widgets: dict[str, QTableWidget] = {}
        self._select_all_cbs: dict[str, QCheckBox] = {}

        for operation, tab_name in TAB_CONFIG:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(4, 4, 4, 4)

            select_all = QCheckBox(f"全选 {tab_name}")
            select_all.setTristate(False)
            select_all.setChecked(True)
            select_all.toggled.connect(
                lambda checked, op=operation: self._on_select_all(op, checked)
            )
            page_layout.addWidget(select_all)
            self._select_all_cbs[operation] = select_all

            table = QTableWidget()
            table.setColumnCount(5)
            table.setHorizontalHeaderLabels(["", "文件名", "源端", "目的端", "方向"])
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.verticalHeader().setVisible(False)

            hdr = table.horizontalHeader()
            hdr.setSectionResizeMode(0, QHeaderView.Interactive)
            table.setColumnWidth(0, 40)
            hdr.setSectionResizeMode(1, QHeaderView.Interactive)
            table.setColumnWidth(1, 220)
            hdr.setSectionResizeMode(2, QHeaderView.Interactive)
            table.setColumnWidth(2, 110)
            hdr.setSectionResizeMode(3, QHeaderView.Interactive)
            table.setColumnWidth(3, 110)
            hdr.setSectionResizeMode(4, QHeaderView.Interactive)
            table.setColumnWidth(4, 150)
            hdr.setStretchLastSection(False)

            page_layout.addWidget(table)
            self._table_widgets[operation] = table
            self._tab_widget.addTab(page, tab_name)

        root.addWidget(self._tab_widget)

    # ── 公共接口 ──

    def load_diffs(self, diffs: list[DiffItem],
                   src_label: str = DEVICE_PC,
                   dst_label: str = DEVICE_PC) -> None:
        self._diffs = diffs
        self._src_label = src_label
        self._dst_label = dst_label

        self._diff_by_operation = {"copy": [], "overwrite": [], "delete": []}
        for d in diffs:
            if d.operation in self._diff_by_operation:
                self._diff_by_operation[d.operation].append(d)

        for operation, tab_name in TAB_CONFIG:
            items = self._diff_by_operation[operation]
            count = len(items)

            idx = self._tab_widget.indexOf(self._table_widgets[operation].parent())
            if idx < 0:
                continue

            if count == 0:
                self._tab_widget.setTabVisible(idx, False)
                continue

            self._tab_widget.setTabVisible(idx, True)
            self._tab_widget.setTabText(idx, f"{tab_name} ({count})")

            select_all = self._select_all_cbs[operation]
            select_all.blockSignals(True)
            select_all.setChecked(True)
            select_all.setTristate(False)
            select_all.blockSignals(False)

            table = self._table_widgets[operation]
            table.setRowCount(count)

            for row, diff in enumerate(sorted(items, key=lambda d: d.relative_path)):
                self._fill_row(table, row, diff)

        self._emit_selection_stats()

    def get_diffs(self) -> list[DiffItem]:
        return list(self._diffs)

    def total_count(self) -> int:
        return len(self._diffs)

    def selected_count(self) -> int:
        return sum(1 for d in self._diffs if d.selected)

    def selected_total_bytes(self) -> int:
        total = 0
        for d in self._diffs:
            if d.selected:
                if d.operation == "delete":
                    total += d.dest_size or 0
                else:
                    total += d.source_size or 0
        return total

    # ── 内部 ──

    def _fill_row(self, table, row, diff) -> None:
        # 复选框
        cb = QCheckBox()
        cb.setChecked(diff.selected)
        cb.stateChanged.connect(lambda state, d=diff: self._on_item_toggled(d, state))
        cb_widget = QWidget()
        cb_layout = QHBoxLayout(cb_widget)
        cb_layout.addWidget(cb)
        cb_layout.setAlignment(Qt.AlignCenter)
        cb_layout.setContentsMargins(0, 0, 0, 0)
        table.setCellWidget(row, 0, cb_widget)

        # 文件名
        path_item = QTableWidgetItem(diff.relative_path)
        path_item.setToolTip(diff.relative_path)
        path_item.setFlags(path_item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, 1, path_item)

        # 源端
        src_text = format_device_size(self._src_label, diff.source_size)
        src_item = QTableWidgetItem(src_text)
        src_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        src_item.setFlags(src_item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, 2, src_item)

        # 目的端
        dst_text = format_device_size(self._dst_label, diff.dest_size)
        dst_item = QTableWidgetItem(dst_text)
        dst_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        dst_item.setFlags(dst_item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, 3, dst_item)

        # 方向
        if diff.operation == "delete":
            dir_text = f"删除 in {self._dst_label}"
        else:
            dir_text = f"{self._src_label} → {self._dst_label}"
        dir_item = QTableWidgetItem(dir_text)
        dir_item.setTextAlignment(Qt.AlignCenter)
        dir_item.setFlags(dir_item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, 4, dir_item)

        table.setRowHeight(row, 28)

    def _on_item_toggled(self, diff, state):
        diff.selected = (state == Qt.Checked.value)
        self._update_select_all(diff.operation)
        self._emit_selection_stats()

    def _on_select_all(self, operation, checked):
        items = self._diff_by_operation.get(operation, [])
        for d in items:
            d.selected = checked
        table = self._table_widgets[operation]
        for row in range(table.rowCount()):
            cb_widget = table.cellWidget(row, 0)
            if cb_widget:
                cb = cb_widget.findChild(QCheckBox)
                if cb:
                    cb.blockSignals(True)
                    cb.setChecked(checked)
                    cb.blockSignals(False)
        self._emit_selection_stats()

    def _update_select_all(self, operation):
        items = self._diff_by_operation.get(operation, [])
        if not items:
            return
        selected = sum(1 for d in items if d.selected)
        select_all = self._select_all_cbs[operation]
        select_all.blockSignals(True)
        if selected == len(items):
            select_all.setCheckState(Qt.Checked)
            select_all.setTristate(False)
        elif selected == 0:
            select_all.setCheckState(Qt.Unchecked)
            select_all.setTristate(False)
        else:
            select_all.setTristate(True)
            select_all.setCheckState(Qt.PartiallyChecked)
        select_all.blockSignals(False)

    def _emit_selection_stats(self):
        self.selection_changed.emit(
            self.total_count(),
            self.selected_count(),
            self.selected_total_bytes(),
        )
