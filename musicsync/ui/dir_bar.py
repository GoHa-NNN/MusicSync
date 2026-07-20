"""路径选择器 — 源/目的双路径选择面板。

组件布局::

    源  [PC ▼]  [________路径输入________]  [清除]  [浏览]
    目的 [Phone ▼] [_______路径输入_______]  [清除]  [浏览]  [开始比对]

功能:
    - 每行输入框右侧有独立的"清除"按钮
    - 输入框聚焦且为空时，通过 QCompleter 自动弹出历史路径下拉选择
    - 设备类型从 Phone 切换到 PC 时自动清空输入框
    - 开始比对时自动将当前路径写入路径记忆（remembered_paths 表）
"""

import os
import sqlite3

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QFileDialog, QCompleter,
)
from PySide6.QtCore import Signal, Qt, QTimer, QStringListModel

from musicsync.store.database import list_remembered_paths, remember_path
from musicsync.ui.utils import logger


PHONE_DEFAULT_PATH = "/sdcard/Music/"


# ---------------------------------------------------------------------------
# _HistoryLineEdit — 带独立清除按钮 + QCompleter 的路径输入框
# ---------------------------------------------------------------------------

class _HistoryLineEdit(QLineEdit):
    """聚焦且为空时自动弹出历史路径下拉的输入框。

    当用户从下拉列表中选择一项后，自动填入该项文本。
    """

    cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._completer = QCompleter([], self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self._completer.setMaxVisibleItems(10)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.activated.connect(self._on_completer_activated)
        self.setCompleter(self._completer)

    def _on_completer_activated(self, text: str) -> None:
        """用户从下拉中选择了一项，填入输入框。"""
        self.setText(text)

    def set_history(self, paths: list[str]) -> None:
        model = QStringListModel(paths, self)
        self._completer.setModel(model)

    def refresh_and_popup(self) -> None:
        """外部通知：历史数据已刷新，可以弹出了。"""
        if not self.text().strip():
            self.setFocus()
            QTimer.singleShot(120, self._show_popup)
        else:
            self.setFocus()

    def clear_and_refresh(self) -> None:
        self.clear()
        self.cleared.emit()
        self.setFocus()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if not self.text().strip():
            m = self._completer.model()
            if m and m.rowCount() > 0:
                QTimer.singleShot(120, self._show_popup)

    def _show_popup(self) -> None:
        """强制弹出下拉框（即使文本为空）。"""
        m = self._completer.model()
        if m and m.rowCount() > 0:
            # 设置空前缀，让 Qt 显示所有项
            self._completer.setCompletionPrefix("")
            self._completer.complete()

    # 补丁：处理 QCompleter 的 popup 中的 click 事件
    # 原生行为在 UnfilteredPopupCompletion 下点击项后不填入文本——
    # 我们通过覆写此钩子来解决。
    # 实际上通过 activated 信号处理了。

    def mousePressEvent(self, event) -> None:
        """点击输入框时，如果是空文本且有历史数据，弹出下拉。"""
        super().mousePressEvent(event)
        if not self.text().strip():
            m = self._completer.model()
            if m and m.rowCount() > 0:
                QTimer.singleShot(120, self._show_popup)


# ---------------------------------------------------------------------------
# DirBar
# ---------------------------------------------------------------------------

class DirBar(QWidget):
    """源/目的双路径选择器。

    对外 emit ``start_compare`` 当用户点击"开始比对"按钮时。
    """

    start_compare = Signal(str, str, str, str)

    def __init__(self, db_path: str = "musicsync.db", parent=None):
        super().__init__(parent)
        self.db_path = db_path

        # ── 源行 ──
        src_row = QHBoxLayout()
        src_row.setSpacing(4)
        src_label = QLabel("  源")
        src_label.setFixedWidth(32)
        self._src_device_combo = QComboBox()
        self._src_device_combo.addItems(["PC", "Phone"])
        self._src_device_combo.setCurrentIndex(0)
        self._src_path_input = _HistoryLineEdit()
        self._src_path_input.setPlaceholderText("源路径…")
        self._src_clear_btn = QPushButton("X")
        self._src_clear_btn.setFixedWidth(32)
        self._src_clear_btn.setToolTip("清空路径并显示历史记录")
        self._src_browse_btn = QPushButton("浏览")

        src_row.addWidget(src_label)
        src_row.addWidget(self._src_device_combo)
        src_row.addWidget(self._src_path_input, 1)
        src_row.addWidget(self._src_clear_btn)
        src_row.addWidget(self._src_browse_btn)

        # ── 目的行 ──
        dst_row = QHBoxLayout()
        dst_row.setSpacing(4)
        dst_label = QLabel("目的")
        dst_label.setFixedWidth(32)
        self._dest_device_combo = QComboBox()
        self._dest_device_combo.addItems(["PC", "Phone"])
        self._dest_device_combo.setCurrentIndex(1)   # 默认 Phone
        self._dest_path_input = _HistoryLineEdit()
        self._dest_path_input.setPlaceholderText("目的路径…")
        self._dest_clear_btn = QPushButton("X")
        self._dest_clear_btn.setFixedWidth(32)
        self._dest_clear_btn.setToolTip("清空路径并显示历史记录")
        self._dest_browse_btn = QPushButton("浏览")
        self._start_btn = QPushButton("  开始比对  ")
        self._start_btn.setEnabled(False)
        self._start_btn.setMinimumWidth(90)

        dst_row.addWidget(dst_label)
        dst_row.addWidget(self._dest_device_combo)
        dst_row.addWidget(self._dest_path_input, 1)
        dst_row.addWidget(self._dest_clear_btn)
        dst_row.addWidget(self._dest_browse_btn)
        dst_row.addWidget(self._start_btn)

        # ── 总布局 ──
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(6)
        root.addLayout(src_row)
        root.addLayout(dst_row)

        # ── 信号连接 ──
        self._src_device_combo.currentIndexChanged.connect(self._on_source_device_changed)
        self._dest_device_combo.currentIndexChanged.connect(self._on_dest_device_changed)
        self._src_browse_btn.clicked.connect(self._on_source_browse)
        self._dest_browse_btn.clicked.connect(self._on_dest_browse)
        self._src_clear_btn.clicked.connect(self._src_path_input.clear_and_refresh)
        self._dest_clear_btn.clicked.connect(self._dest_path_input.clear_and_refresh)
        self._src_path_input.textChanged.connect(self._check_ready)
        self._dest_path_input.textChanged.connect(self._check_ready)
        self._src_path_input.cleared.connect(lambda: self._load_and_pop_src())
        self._dest_path_input.cleared.connect(lambda: self._load_and_pop_dst())
        self._start_btn.clicked.connect(self._on_start)

        # ── 初始化 ──
        self._on_source_device_changed(0)
        self._on_dest_device_changed(1)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def source_device_type(self) -> str:
        return "phone" if self._src_device_combo.currentIndex() == 1 else "pc"

    def source_path(self) -> str:
        return self._src_path_input.text().strip()

    def dest_device_type(self) -> str:
        return "phone" if self._dest_device_combo.currentIndex() == 1 else "pc"

    def dest_path(self) -> str:
        return self._dest_path_input.text().strip()

    # ------------------------------------------------------------------
    # 内部槽
    # ------------------------------------------------------------------

    def _on_source_device_changed(self, index: int) -> None:
        if index == 1:  # Phone
            self._src_path_input.setText(PHONE_DEFAULT_PATH)
            self._src_browse_btn.setEnabled(False)
        else:  # PC
            self._src_path_input.clear_and_refresh()   # 清空，emits cleared → _load_and_pop_src
            self._src_browse_btn.setEnabled(True)
        self._load_src_history()
        self._check_ready()

    def _on_dest_device_changed(self, index: int) -> None:
        if index == 1:  # Phone
            self._dest_path_input.setText(PHONE_DEFAULT_PATH)
            self._dest_browse_btn.setEnabled(False)
        else:  # PC
            self._dest_path_input.clear_and_refresh()   # 清空，emits cleared → _load_and_pop_dst
            self._dest_browse_btn.setEnabled(True)
        self._load_dst_history()
        self._check_ready()

    def _on_source_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择源文件夹")
        if path:
            self._src_path_input.setText(os.path.normpath(path))

    def _on_dest_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择目的文件夹")
        if path:
            self._dest_path_input.setText(os.path.normpath(path))

    def _check_ready(self) -> None:
        src = self._src_path_input.text().strip()
        dst = self._dest_path_input.text().strip()
        self._start_btn.setEnabled(bool(src) and bool(dst))

    def _on_start(self) -> None:
        src_device = self.source_device_type()
        src_path = self.source_path()
        dst_device = self.dest_device_type()
        dst_path = self.dest_path()

        # 写入路径记忆
        try:
            conn = sqlite3.connect(self.db_path)
            remember_path(conn, src_device, src_path, "source")
            remember_path(conn, dst_device, dst_path, "dest")
            conn.close()
        except Exception:
            pass

        logger.info(
            "DirBar: 开始比对 — 源(%s): %s → 目的(%s): %s",
            src_device, src_path, dst_device, dst_path,
        )
        self.start_compare.emit(src_device, src_path, dst_device, dst_path)

    # ------------------------------------------------------------------
    # 历史路径加载
    # ------------------------------------------------------------------

    def _load_src_history(self) -> None:
        device_type = self.source_device_type()
        try:
            conn = sqlite3.connect(self.db_path)
            paths = list_remembered_paths(conn, device_type, "source", limit=10)
            conn.close()
            self._src_path_input.set_history(paths)
        except Exception:
            self._src_path_input.set_history([])

    def _load_dst_history(self) -> None:
        device_type = self.dest_device_type()
        try:
            conn = sqlite3.connect(self.db_path)
            paths = list_remembered_paths(conn, device_type, "dest", limit=10)
            conn.close()
            self._dest_path_input.set_history(paths)
        except Exception:
            self._dest_path_input.set_history([])

    def _load_and_pop_src(self) -> None:
        """加载源端历史 → 弹出下拉。"""
        self._load_src_history()
        self._src_path_input.refresh_and_popup()

    def _load_and_pop_dst(self) -> None:
        """加载目的端历史 → 弹出下拉。"""
        self._load_dst_history()
        self._dest_path_input.refresh_and_popup()
