"""操作历史面板 — 带筛选工具栏、日期分隔行和分页控件。

工具栏: [今天] 从 [QDateEdit] 到 [QDateEdit] | 搜索框 | [清除]
表格: 时间 | 操作 | 文件名 | 大小，按日期插入分隔行
分页: |◀ ◀ 第 X/Y 页 ▶ ▶|
"""

import sqlite3
from datetime import datetime, timezone, timedelta, date as date_type

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPushButton, QLabel, QLineEdit,
    QDateEdit,
)
from PySide6.QtCore import Qt, QTimer, QDate
from PySide6.QtGui import QColor

from musicsync.adb_device_kit.executor_helpers import format_size
from musicsync.store.database import list_operations_filtered

PAGE_SIZE = 30
SEARCH_DEBOUNCE_MS = 300


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
    """操作历史表格 — 带筛选工具栏、日期分隔行和分页控件。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── 状态 ──
        self._conn: sqlite3.Connection | None = None
        self._page = 1
        self._total_pages = 1
        self._filters_active = False

        # ── 搜索防抖定时器 ──
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._on_search_timer)

        # ── 根布局 ──
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── 工具栏行 ──
        self._build_toolbar(root)

        # ── 表格 ──
        self._build_table(root)

        # ── 分页栏 ──
        self._build_pagination(root)

    # ────────────────────────────────────────────────
    #  工具栏
    # ────────────────────────────────────────────────

    def _build_toolbar(self, root: QVBoxLayout) -> None:
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        self._today_btn = QPushButton("今天")
        self._today_btn.setFixedWidth(60)
        self._today_btn.clicked.connect(self._on_today)
        toolbar.addWidget(self._today_btn)

        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDisplayFormat("yyyy-MM-dd")
        self._date_from.setDate(QDate.currentDate())
        self._date_from.setFixedWidth(120)
        self._date_from.dateChanged.connect(self._on_date_changed)
        toolbar.addWidget(self._date_from)

        sep_label = QLabel("—")
        sep_label.setAlignment(Qt.AlignCenter)
        toolbar.addWidget(sep_label)

        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDisplayFormat("yyyy-MM-dd")
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setFixedWidth(120)
        self._date_to.dateChanged.connect(self._on_date_changed)
        toolbar.addWidget(self._date_to)

        toolbar.addStretch()

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("搜索文件名…")
        self._search_edit.setMaximumWidth(260)
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self._search_edit, 1)

        self._clear_btn = QPushButton("清除")
        self._clear_btn.setFixedWidth(50)
        self._clear_btn.clicked.connect(self._on_clear_filters)
        toolbar.addWidget(self._clear_btn)

        root.addLayout(toolbar)

    # ── 工具栏槽 ──

    def _on_today(self) -> None:
        """今天按钮：填充日期选择器为当天并加载。"""
        today = QDate.currentDate()
        self._date_from.blockSignals(True)
        self._date_from.setDate(today)
        self._date_from.blockSignals(False)
        self._date_to.blockSignals(True)
        self._date_to.setDate(today)
        self._date_to.blockSignals(False)
        self._filters_active = True
        self._load_page(1)

    def _on_date_changed(self) -> None:
        """日期范围变更时重新查询。"""
        self._filters_active = True
        self._load_page(1)

    def _on_search_changed(self, _text: str) -> None:
        """搜索文本变更时启动防抖定时器。"""
        self._search_timer.start(SEARCH_DEBOUNCE_MS)

    def _on_search_timer(self) -> None:
        """防抖定时器触发，执行搜索查询。"""
        self._load_page(1)

    def _on_clear_filters(self) -> None:
        """清除所有筛选条件，恢复默认状态。"""
        self._search_edit.clear()
        self._filters_active = False
        today = QDate.currentDate()
        self._date_from.blockSignals(True)
        self._date_from.setDate(today)
        self._date_from.blockSignals(False)
        self._date_to.blockSignals(True)
        self._date_to.setDate(today)
        self._date_to.blockSignals(False)
        self._load_page(1)

    # ────────────────────────────────────────────────
    #  表格
    # ────────────────────────────────────────────────

    def _build_table(self, root: QVBoxLayout) -> None:
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

        root.addWidget(self._table, 1)

    # ────────────────────────────────────────────────
    #  分页栏
    # ────────────────────────────────────────────────

    def _build_pagination(self, root: QVBoxLayout) -> None:
        pager = QHBoxLayout()
        pager.setSpacing(4)
        pager.setAlignment(Qt.AlignCenter)

        self._first_btn = QPushButton("|◀")
        self._first_btn.setFixedWidth(36)
        self._first_btn.clicked.connect(lambda: self._load_page(1))
        pager.addWidget(self._first_btn)

        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedWidth(36)
        self._prev_btn.clicked.connect(lambda: self._load_page(self._page - 1))
        pager.addWidget(self._prev_btn)

        self._page_label = QLabel("第 1/1 页")
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setMinimumWidth(80)
        pager.addWidget(self._page_label)

        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedWidth(36)
        self._next_btn.clicked.connect(lambda: self._load_page(self._page + 1))
        pager.addWidget(self._next_btn)

        self._last_btn = QPushButton("▶|")
        self._last_btn.setFixedWidth(36)
        self._last_btn.clicked.connect(lambda: self._load_page(self._total_pages))
        pager.addWidget(self._last_btn)

        root.addLayout(pager)

    # ────────────────────────────────────────────────
    #  公共接口
    # ────────────────────────────────────────────────

    def refresh(self, conn: sqlite3.Connection) -> None:
        """重置所有筛选条件并加载第 1 页（无筛选 = 显示全部）。"""
        self._conn = conn
        self._filters_active = False
        self._search_edit.clear()
        today = QDate.currentDate()
        self._date_from.blockSignals(True)
        self._date_from.setDate(today)
        self._date_from.blockSignals(False)
        self._date_to.blockSignals(True)
        self._date_to.setDate(today)
        self._date_to.blockSignals(False)
        self._load_page(1)

    # ────────────────────────────────────────────────
    #  核心加载逻辑
    # ────────────────────────────────────────────────

    def _load_page(self, page: int) -> None:
        """根据当前筛选状态查询数据库并填充表格。"""
        if self._conn is None:
            return

        page = max(page, 1)

        # 构建 UTC 日期边界
        date_from_utc = None
        date_to_utc = None
        if self._filters_active:
            from_date = self._date_from.date().toPython()
            to_date = self._date_to.date().toPython()
            date_from_utc = self._local_date_to_utc_bound(from_date, is_end=False)
            # to 日期需包含当天全天 → 上界为次日 00:00 UTC
            date_to_utc = self._local_date_to_utc_bound(to_date, is_end=True)

        search = self._search_edit.text().strip() or None

        records, total = list_operations_filtered(
            self._conn,
            page=page,
            page_size=PAGE_SIZE,
            date_from=date_from_utc,
            date_to=date_to_utc,
            search=search,
        )

        # 页码 clamp：如果当前页超出范围，回退到最后一页
        self._total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if page > self._total_pages:
            page = self._total_pages
            # 递归重载最后一页
            records, total = list_operations_filtered(
                self._conn,
                page=page,
                page_size=PAGE_SIZE,
                date_from=date_from_utc,
                date_to=date_to_utc,
                search=search,
            )

        self._page = page
        self._total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self._populate_table(records)
        self._update_pagination_controls()

    def _populate_table(self, records: list[dict]) -> None:
        """填充表格 — 按日期插入分隔行。"""
        if not records:
            self._table.setRowCount(0)
            return

        # 首遍历：确定哪行需要日期分隔行
        rows_with_seps: list[tuple[dict, str, bool]] = []
        prev_date = None
        for r in records:
            try:
                dt = datetime.fromisoformat(r["timestamp"])
                if dt.tzinfo is not None:
                    dt = dt.astimezone()
                row_date = dt.strftime("%Y-%m-%d")
            except Exception:
                row_date = r["timestamp"][:10]
            need_sep = (prev_date is None or row_date != prev_date)
            rows_with_seps.append((r, row_date, need_sep))
            prev_date = row_date

        sep_count = sum(1 for _, _, need in rows_with_seps if need)
        total_rows = len(records) + sep_count
        self._table.setRowCount(total_rows)

        table_row = 0
        for r, row_date, need_sep in rows_with_seps:
            if need_sep:
                self._insert_date_separator(table_row, row_date)
                table_row += 1
            self._fill_data_row(table_row, r)
            self._table.setRowHeight(table_row, 24)
            table_row += 1

    def _insert_date_separator(self, row: int, date_str: str) -> None:
        """在指定行插入日期分隔行。"""
        sep_item = QTableWidgetItem(f"──── {date_str} ────")
        sep_item.setBackground(QColor("#e8e8e8"))
        sep_item.setForeground(QColor("#555555"))
        sep_item.setTextAlignment(Qt.AlignCenter)
        sep_item.setFlags(Qt.NoItemFlags)
        self._table.setSpan(row, 0, 1, 4)
        self._table.setItem(row, 0, sep_item)
        self._table.setRowHeight(row, 22)

    def _fill_data_row(self, row: int, r: dict) -> None:
        """填充单行数据（从现有逻辑提取，不变）。"""
        # 时间
        ts = r["timestamp"]
        try:
            dt = datetime.fromisoformat(ts)
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

    # ────────────────────────────────────────────────
    #  分页控件更新
    # ────────────────────────────────────────────────

    def _update_pagination_controls(self) -> None:
        """根据当前页码/总页数更新按钮启用状态。"""
        self._page_label.setText(f"第 {self._page}/{self._total_pages} 页")
        on_first = self._page <= 1
        on_last = self._page >= self._total_pages
        self._first_btn.setEnabled(not on_first)
        self._prev_btn.setEnabled(not on_first)
        self._next_btn.setEnabled(not on_last)
        self._last_btn.setEnabled(not on_last)

    # ────────────────────────────────────────────────
    #  时区工具
    # ────────────────────────────────────────────────

    @staticmethod
    def _local_date_to_utc_bound(d: date_type, is_end: bool = False) -> str:
        """本地日期 → UTC ISO 8601 边界字符串。

        Args:
            d: 本地日期
            is_end: False → 当天 00:00 本地 → UTC（闭区间下界）
                    True  → 次日 00:00 本地 → UTC（开区间上界）
        """
        local_tz = datetime.now().astimezone().tzinfo
        if is_end:
            d = d + timedelta(days=1)
        local_dt = datetime.combine(d, datetime.min.time()).replace(tzinfo=local_tz)
        utc_dt = local_dt.astimezone(timezone.utc)
        return utc_dt.isoformat()
