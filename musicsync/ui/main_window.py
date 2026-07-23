"""主窗口 — 单表格切换布局 + 四状态状态机。

布局::

    ┌─────────────────────────────────────────────────┐
    │  DirBar（源/目的路径选择 + 开始比对）            │
    ├─────────────────────────────────────────────────┤
    │  [📋 差异列表]  [📜 操作历史]     ← 切换按钮   │
    │  ┌─────────────────────────────────────────┐   │
    │  │         表格区域（差异/历史二选一）       │   │
    │  └─────────────────────────────────────────┘   │
    ├─────────────────────────────────────────────────┤
    │    [=========进度条=========] 统计              │
    │                              [执行同步] [取消]  │
    └─────────────────────────────────────────────────┘
"""

import os
import copy
import sqlite3
from enum import Enum

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QMessageBox, QStackedWidget, QLabel,
    QFrame,
)
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QCloseEvent

from musicsync.ui.dir_bar import DirBar
from musicsync.ui.diff_view import DiffView
from musicsync.ui.history_view import HistoryView
from musicsync.ui.status_bar import StatusBar
from musicsync.ui.workers import ScanWorker, CompareWorker, ExecuteWorker
from musicsync.ui.utils import logger, set_status_warning

from musicsync.adb_device_kit.cancel_flag import CancelFlag
from musicsync.adb_device_kit.device import Device
from musicsync.adb_device_kit.filter_utils import DEFAULT_AUDIO_EXTENSIONS
from musicsync.store.database import init_db, record_operation

# emoji
PC_LABEL  = "[PC]"
PH_LABEL  = "[Phone]"


class SyncState(Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    REVIEWING = "reviewing"
    EXECUTING = "executing"


class MainWindow(QMainWindow):
    def __init__(self, db_path: str = "musicsync.db"):
        super().__init__()
        self.setWindowTitle("MusicSync — 单向镜像音乐文件夹同步")
        self.setMinimumSize(900, 550)
        self.resize(1100, 650)

        self.db_path = db_path
        self._state = SyncState.IDLE
        self._cancel_flag = CancelFlag()

        self._db_conn = sqlite3.connect(db_path, check_same_thread=False)
        self._db_conn.execute("PRAGMA journal_mode=WAL")
        init_db(self._db_conn)

        self._scan_thread = None
        self._scan_worker = None
        self._compare_thread = None
        self._compare_worker = None
        self._execute_thread = None
        self._execute_worker = None

        self._source_files = []
        self._dest_files = []
        self._src_skipped = None

        self._current_src_root = ""
        self._current_dst_root = ""
        self._current_src_device = ""
        self._current_dst_device = ""

        # ── 中央 widget ──
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # ── DirBar ──
        self.dir_bar = DirBar(db_path=db_path)
        root.addWidget(self.dir_bar)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # ── 切换按钮行 ──
        switch_row = QHBoxLayout()
        switch_row.setSpacing(4)
        self._diff_btn = QPushButton("差异列表")
        self._diff_btn.setCheckable(True)
        self._diff_btn.setChecked(True)
        self._diff_btn.setMinimumWidth(100)
        self._hist_btn = QPushButton("操作历史")
        self._hist_btn.setCheckable(True)
        self._hist_btn.setMinimumWidth(100)
        switch_row.addWidget(self._diff_btn)
        switch_row.addWidget(self._hist_btn)
        switch_row.addStretch()
        root.addLayout(switch_row)

        # ── 表格堆栈：差异/历史二选一 ──
        self._stack = QStackedWidget()
        self.diff_view = DiffView()
        self.history_view = HistoryView()
        self._stack.addWidget(self.diff_view)    # index 0
        self._stack.addWidget(self.history_view)  # index 1
        self._stack.setCurrentIndex(0)
        root.addWidget(self._stack, 1)

        # ── 底部按钮行 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._execute_btn = QPushButton("执行同步")
        self._execute_btn.setEnabled(False)
        self._execute_btn.setMinimumWidth(120)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.setMinimumWidth(90)
        self._cancel_btn.setVisible(False)
        btn_row.addWidget(self._execute_btn)
        btn_row.addWidget(self._cancel_btn)
        root.addLayout(btn_row)

        # ── 状态栏 ──
        self.status_bar = StatusBar()
        self.setStatusBar(self.status_bar)

        # ── 信号连接 ──
        self.dir_bar.start_compare.connect(self._on_start_compare)
        self._execute_btn.clicked.connect(self._on_execute)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self.diff_view.selection_changed.connect(self._on_selection_changed)
        self._diff_btn.clicked.connect(lambda: self._switch_view(0))
        self._hist_btn.clicked.connect(lambda: self._switch_view(1))

        self._apply_state(SyncState.IDLE)
        self.history_view.refresh(self._db_conn)

        logger.info("MainWindow: 初始化完成")

    # ── 视图切换 ──

    def _switch_view(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._diff_btn.setChecked(index == 0)
        self._hist_btn.setChecked(index == 1)
        if index == 1:
            self.history_view.refresh(self._db_conn)

    # ── 状态机 ──

    def _apply_state(self, state: SyncState) -> None:
        self._state = state
        logger.debug("MainWindow: 状态 → %s", state.value)

        if state == SyncState.IDLE:
            self.dir_bar.setEnabled(True)
            self._stack.setEnabled(True)      # ← 允许看历史
            self._diff_btn.setEnabled(True)
            self._hist_btn.setEnabled(True)
            self._execute_btn.setEnabled(False)
            self._cancel_btn.setVisible(False)
            self._cancel_flag.reset()

        elif state == SyncState.SCANNING:
            self.dir_bar.setEnabled(False)
            self._stack.setEnabled(False)
            self._diff_btn.setEnabled(False)
            self._hist_btn.setEnabled(False)
            self._execute_btn.setEnabled(False)
            self._cancel_btn.setVisible(True)
            self._cancel_btn.setEnabled(True)

        elif state == SyncState.REVIEWING:
            self.dir_bar.setEnabled(True)
            self._stack.setEnabled(True)
            self._diff_btn.setEnabled(True)
            self._hist_btn.setEnabled(True)
            self._execute_btn.setEnabled(True)
            self._cancel_btn.setVisible(False)
            self.status_bar.set_warning("", "INFO")

        elif state == SyncState.EXECUTING:
            self.dir_bar.setEnabled(False)
            self._stack.setEnabled(False)
            self._diff_btn.setEnabled(False)
            self._hist_btn.setEnabled(False)
            self._execute_btn.setEnabled(False)
            self._cancel_btn.setVisible(True)
            self._cancel_btn.setEnabled(True)

    # ── 开始比对 ──

    def _on_start_compare(self, src_device_type, src_path, dst_device_type, dst_path):
        if not os.path.isdir(src_path) and src_device_type == "pc":
            QMessageBox.warning(self, "路径错误", f"源路径不存在：\n{src_path}")
            return
        if not os.path.isdir(dst_path) and dst_device_type == "pc":
            QMessageBox.warning(self, "路径错误", f"目的路径不存在：\n{dst_path}")
            return

        self._current_src_root = src_path
        self._current_dst_root = dst_path
        self._current_src_device = src_device_type
        self._current_dst_device = dst_device_type

        self._apply_state(SyncState.SCANNING)
        self.status_bar.update_progress("scan", "source", 0, 0, "")
        self.status_bar.set_warning("", "INFO")

        source_device = self._mk_device(src_device_type)
        dest_device = self._mk_device(dst_device_type)
        extensions = list(DEFAULT_AUDIO_EXTENSIONS)

        self._cancel_flag.reset()
        self._scan_worker = ScanWorker(
            source_root=src_path,
            source_extensions=extensions,
            dest_root=dst_path,
            dest_extensions=extensions,
            source_device=source_device,
            dest_device=dest_device,
            cancel_flag=self._cancel_flag,
        )
        self._scan_thread = QThread()
        self._scan_worker.moveToThread(self._scan_thread)

        assert self._scan_worker.progress.connect(self.status_bar.update_progress)
        assert self._scan_worker.finished.connect(self._on_scan_finished)
        assert self._scan_worker.error.connect(self._on_worker_error)

        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_scan_finished(self, source_files, dest_files, skipped):
        self._source_files = source_files
        self._dest_files = dest_files
        self._src_skipped = skipped

        if skipped.total > 0:
            self.status_bar.set_warning(f"已跳过 {skipped.total} 个非音频文件", "WARNING")
        else:
            self.status_bar.set_warning("", "INFO")

        self.status_bar.update_progress("compare", "comparing", 0, 1, "")

        self._compare_worker = CompareWorker(
            source_files=copy.deepcopy(self._source_files),
            dest_files=copy.deepcopy(self._dest_files),
            cancel_flag=self._cancel_flag,
        )
        self._compare_thread = QThread()
        self._compare_worker.moveToThread(self._compare_thread)

        assert self._compare_worker.progress.connect(self.status_bar.update_progress)
        assert self._compare_worker.finished.connect(self._on_compare_finished)
        assert self._compare_worker.error.connect(self._on_worker_error)

        self._compare_thread.started.connect(self._compare_worker.run)
        self._compare_worker.finished.connect(self._compare_thread.quit)
        self._compare_worker.finished.connect(self._compare_worker.deleteLater)
        self._compare_thread.finished.connect(self._compare_thread.deleteLater)
        self._compare_thread.start()

    def _on_compare_finished(self, diffs):
        # 确定设备 emoji
        src_emoji = PH_LABEL if self._current_src_device == "phone" else PC_LABEL
        dst_emoji = PH_LABEL if self._current_dst_device == "phone" else PC_LABEL

        self.diff_view.load_diffs(diffs, src_label=src_emoji, dst_label=dst_emoji)
        self._switch_view(0)  # 自动切到差异视图
        self._apply_state(SyncState.REVIEWING)

        # 刷新历史（供手动切换到历史标签时查看最新数据）
        self.history_view.refresh(self._db_conn)

        if len(diffs) == 0:
            self.status_bar.showMessage("两端完全一致，无需同步！")
        else:
            self.status_bar.showMessage(f"发现 {len(diffs)} 项差异，请审核后点击「执行同步」")

    # ── 执行同步 ──

    def _on_execute(self):
        diffs = self.diff_view.get_diffs()
        selected = [d for d in diffs if d.selected]
        if not selected:
            QMessageBox.information(self, "提示", "没有勾选任何项目，无需执行。")
            return

        self._apply_state(SyncState.EXECUTING)
        self.status_bar.set_warning("", "INFO")

        source_device = self._mk_device(self._current_src_device)
        dest_device = self._mk_device(self._current_dst_device)
        self._cancel_flag.reset()

        # 清除之前的失败标签页
        for i in range(self._left_tabs.count() - 1, 0, -1) if hasattr(self, '_left_tabs') else []:
            if self._left_tabs.tabText(i).startswith("失败"):
                self._left_tabs.removeTab(i)

        self._execute_worker = ExecuteWorker(
            diffs, self._current_src_root, self._current_dst_root,
            source_device=source_device,
            dest_device=dest_device,
            cancel_flag=self._cancel_flag,
        )
        self._execute_thread = QThread()
        self._execute_worker.moveToThread(self._execute_thread)

        assert self._execute_worker.progress.connect(self.status_bar.update_progress)
        assert self._execute_worker.finished.connect(self._on_execute_finished)
        assert self._execute_worker.error.connect(self._on_worker_error)

        self._execute_thread.started.connect(self._execute_worker.run)
        self._execute_worker.finished.connect(self._execute_thread.quit)
        self._execute_worker.finished.connect(self._execute_worker.deleteLater)
        self._execute_thread.finished.connect(self._execute_thread.deleteLater)
        self._execute_thread.start()

    def _on_execute_finished(self, result):
        # 持久化成功操作
        src_label = "PC" if self._current_src_device == "pc" else "Phone"
        dst_label = "PC" if self._current_dst_device == "pc" else "Phone"

        diffs = self.diff_view.get_diffs()
        for d in diffs:
            if d.selected:
                try:
                    # 构造含设备标签的 direction
                    if d.operation == "delete":
                        direction = dst_label
                    else:
                        direction = f"{src_label} → {dst_label}"

                    record_operation(
                        self._db_conn,
                        action_type=d.operation,
                        direction=direction,
                        relative_path=d.relative_path,
                        file_size=d.source_size or d.dest_size or 0,
                        dest_size=d.dest_size if d.operation == "overwrite" else None,
                    )
                except Exception:
                    logger.exception(
                        "记录操作历史失败: %s %s", d.operation, d.relative_path
                    )

        self.history_view.refresh(self._db_conn)

        msg = (f"完成：{result.success_count} 成功"
               f"  |  {result.failure_count} 失败"
               f"  |  {result.skip_count} 跳过")
        self.status_bar.showMessage(msg)

        if result.failure_count > 0:
            self.status_bar.set_warning(f"{result.failure_count} 项操作失败", "ERROR")
        else:
            self.status_bar.set_warning("", "INFO")

        # 弹窗汇总
        QMessageBox.information(
            self,
            "同步完成",
            f"{msg}\n\n"
            f"差异列表将自动刷新以反映最新状态。",
        )

        # 自动重新比对，刷新差异列表
        self._on_start_compare(
            self._current_src_device,
            self._current_src_root,
            self._current_dst_device,
            self._current_dst_root,
        )

    # ── 取消 ──

    def _on_cancel(self):
        self._cancel_flag.cancel()
        self._cancel_btn.setEnabled(False)
        self.status_bar.set_warning("正在取消…", "WARNING")

    def _on_worker_error(self, error_msg):
        logger.error("Worker 错误: %s", error_msg)
        self.status_bar.set_warning(error_msg, "ERROR")
        if self._state == SyncState.EXECUTING:
            self._apply_state(SyncState.REVIEWING)
        else:
            self._apply_state(SyncState.IDLE)

    def _on_selection_changed(self, total, selected, estimated_bytes):
        self.status_bar.set_stats(total, selected, estimated_bytes)

    # ── 关闭 ──

    def closeEvent(self, event: QCloseEvent):
        """优雅关闭 —三层防线。

        IDLE/REVIEWING: 直接退出。
        SCANNING/EXECUTING: 发取消信号 → 等线程最多 5 秒 → 仍卡死则 terminate。
        """
        if self._state in (SyncState.IDLE, SyncState.REVIEWING):
            logger.info("MainWindow: 正在关闭（状态=%s）", self._state.value)
            self._cleanup_db()
            self._db_conn.close()
            event.accept()
            return

        # ── 防线 1：发取消信号 ──
        logger.info("MainWindow: 发送取消信号后关闭（状态=%s）", self._state.value)
        self._cancel_flag.cancel()

        # ── 防线 2：等线程结束 ──
        threads = []
        for attr in ("_scan_thread", "_compare_thread", "_execute_thread"):
            t = getattr(self, attr, None)
            if t is None:
                continue
            try:
                if t.isRunning():
                    threads.append(t)
                    t.quit()
            except RuntimeError:
                # C++ 对象已被 deleteLater 清理
                logger.debug("MainWindow: %s 已释放", attr)

        import time
        deadline = time.monotonic() + 5.0
        for t in threads:
            remaining = max(0, deadline - time.monotonic())
            if remaining > 0:
                t.wait(int(remaining * 1000))

        # ── 防线 3：硬超时兜底 ──
        for t in threads:
            try:
                if t.isRunning():
                    logger.warning("MainWindow: 线程 %s 超时，强制 terminate", t.objectName())
                    t.terminate()
                    t.wait(1000)
            except RuntimeError:
                pass

        self._db_conn.close()
        event.accept()

    def _cleanup_db(self):
        try:
            self._db_conn.execute("DELETE FROM session_diff")
            self._db_conn.commit()
        except Exception:
            pass

    def _mk_device(self, device_type: str):
        if device_type == "phone":
            return Device("adb")
        return None
