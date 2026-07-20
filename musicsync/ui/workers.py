"""Worker 线程层 — QThread + QObject Worker + Signal/Slot。

三个 Worker 各自运行在独立 QThread 中，通过 Signal 与主线程通信。
所有跨线程 Signal 传递的数据均经过 ``copy.deepcopy`` 深拷贝。

Worker:
    ScanWorker — 调用 ``scan()``，异步返回两端文件列表
    CompareWorker — 调用 ``compare()``，异步返回差异列表
    ExecuteWorker — 调用 ``execute()``，异步返回执行结果

Progress Signal 格式（统一）:
    ``progress(str, str, int, int, str)``
    - stage ∈ {"scan", "compare", "execute"}
    - phase ∈ {"source", "dest", "comparing", "transferring", "deleting", "done"}
    - current: int  当前进度
    - total: int    总数
    - detail: str   正在处理的文件名或空字符串
"""

import copy
from typing import Optional

from PySide6.QtCore import QObject, Signal, QThread

from musicsync.core.sync_engine import scan, compare
from musicsync.core.executor import execute
from musicsync.adb_device_kit.models import ActionResult, SkippedInfo
from musicsync.adb_device_kit.cancel_flag import CancelFlag, CancelledError
from musicsync.core.models import DiffItem
from musicsync.ui.utils import logger


# ---------------------------------------------------------------------------
# ScanWorker
# ---------------------------------------------------------------------------

class ScanWorker(QObject):
    """在独立 QThread 中调用 ``scan()`` 扫描两端文件。

    通过 progress Signal 报告阶段进度，finished Signal 携带两端文件列表。

    用法::

        flag = CancelFlag()
        thread = QThread()
        worker = ScanWorker(src_root, src_exts, dest_root, dest_exts, ..., flag)
        worker.moveToThread(thread)
        worker.finished.connect(on_finished)
        worker.progress.connect(on_progress)
        thread.started.connect(worker.run)
        thread.start()
    """

    finished = Signal(object, object, object)  # (source_files, dest_files, src_skipped)
    progress = Signal(str, str, int, int, str)
    error = Signal(str)

    def __init__(
        self,
        source_root: str,
        source_extensions: list[str],
        dest_root: str,
        dest_extensions: list[str],
        source_musicignore_rules: Optional[list[str]] = None,
        dest_musicignore_rules: Optional[list[str]] = None,
        source_device=None,
        dest_device=None,
        cancel_flag: Optional[CancelFlag] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.source_root = source_root
        self.source_extensions = source_extensions
        self.dest_root = dest_root
        self.dest_extensions = dest_extensions
        self.source_musicignore_rules = source_musicignore_rules
        self.dest_musicignore_rules = dest_musicignore_rules
        self.source_device = source_device
        self.dest_device = dest_device
        self.cancel_flag = cancel_flag or CancelFlag()

    def run(self) -> None:
        """扫描源端和目的端，完成后通过 finished 信号返回结果。

        此方法在 QThread 中执行——不创建 GUI 对象，不操作 widget。
        """
        try:
            # —— 阶段 0：发送开始信号 ——
            self.progress.emit("scan", "source", 0, 0, "")
            self.progress.emit("scan", "dest", 0, 0, "")

            # 定义一个回调：把 progress_callback 信号桥接到 Signal
            def on_progress(stage: str, phase: str, current: int, total: int, detail: str):
                if self.cancel_flag.is_set():
                    raise CancelledError("操作已被取消")
                self.progress.emit(stage, phase, current, total, detail)

            # —— 阶段 1：扫描源端 ——
            logger.info("ScanWorker: 开始扫描源端 %s", self.source_root)
            source_files, src_skipped = scan(
                self.source_root,
                self.source_extensions,
                musicignore_rules=self.source_musicignore_rules,
                device=self.source_device,
                cancel_flag=self.cancel_flag,
                progress_callback=on_progress,
            )
            if self.cancel_flag.is_set():
                self.progress.emit("scan", "done", 0, 0, "")
                return

            # —— 阶段 2：扫描目的端 ——
            logger.info("ScanWorker: 开始扫描目的端 %s", self.dest_root)
            dest_files, dst_skipped = scan(
                self.dest_root,
                self.dest_extensions,
                musicignore_rules=self.dest_musicignore_rules,
                device=self.dest_device,
                cancel_flag=self.cancel_flag,
                progress_callback=on_progress,
            )
            if self.cancel_flag.is_set():
                self.progress.emit("scan", "done", 0, 0, "")
                return

            self.progress.emit("scan", "done",
                               len(source_files) + len(dest_files),
                               len(source_files) + len(dest_files), "")

            # —— 发送结果（深拷贝，防止 Worker 线程后续操作污染） ——
            result_src = copy.deepcopy(source_files)
            result_dst = copy.deepcopy(dest_files)
            result_skipped = copy.deepcopy(src_skipped)
            # 合并两端 skipped 信息
            result_skipped.total += dst_skipped.total
            for ext, count in dst_skipped.by_extension.items():
                result_skipped.by_extension[ext] = result_skipped.by_extension.get(ext, 0) + count
            result_skipped.file_list.extend(dst_skipped.file_list)

            logger.info(
                "ScanWorker: 扫描完成 — 源端 %d 文件, 目的端 %d 文件, 跳过 %d",
                len(source_files), len(dest_files), result_skipped.total,
            )
            self.finished.emit(result_src, result_dst, result_skipped)

        except CancelledError:
            logger.info("ScanWorker: 已被取消")
            self.progress.emit("scan", "done", 0, 0, "")
        except Exception:
            logger.exception("ScanWorker: 异常")
            self.error.emit(f"扫描失败: {logger}")


# ---------------------------------------------------------------------------
# CompareWorker
# ---------------------------------------------------------------------------

class CompareWorker(QObject):
    """在独立 QThread 中调用 ``compare()`` 比对两端文件。

    比对是纯内存操作（~0.1 秒），不发送逐条 progress。
    finished Signal 携带 DiffItem 列表。

    用法::

        worker = CompareWorker(source_files, dest_files, cancel_flag)
        worker.finished.connect(on_compare_done)
    """

    finished = Signal(object)  # list[DiffItem]（深拷贝）
    progress = Signal(str, str, int, int, str)
    error = Signal(str)

    def __init__(
        self,
        source_files: list,
        dest_files: list,
        cancel_flag: Optional[CancelFlag] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.source_files = source_files
        self.dest_files = dest_files
        self.cancel_flag = cancel_flag or CancelFlag()

    def run(self) -> None:
        """比对两端文件，通过 finished 信号返回差异列表。"""
        try:
            self.progress.emit("compare", "comparing", 0, 1, "")

            diffs = compare(self.source_files, self.dest_files, self.cancel_flag)

            if self.cancel_flag.is_set():
                self.progress.emit("compare", "done", 0, 0, "")
                return

            result = copy.deepcopy(diffs)
            logger.info("CompareWorker: 比对完成 — %d 项差异", len(result))
            self.progress.emit("compare", "done", 1, 1, "")
            self.finished.emit(result)

        except Exception:
            logger.exception("CompareWorker: 异常")
            self.error.emit(f"比对失败: {logger}")


# ---------------------------------------------------------------------------
# ExecuteWorker
# ---------------------------------------------------------------------------

class ExecuteWorker(QObject):
    """在独立 QThread 中调用 ``execute()`` 执行同步操作。

    通过 progress Signal 报告逐文件进度，finished Signal 携带 ActionResult。

    用法::

        worker = ExecuteWorker(diffs, src_root, dest_root, src_device, dest_device, flag)
        worker.finished.connect(on_execute_done)
    """

    finished = Signal(object)  # ActionResult（深拷贝）
    progress = Signal(str, str, int, int, str)
    error = Signal(str)

    def __init__(
        self,
        diffs: list[DiffItem],
        source_root: str,
        dest_root: str,
        source_device=None,
        dest_device=None,
        backup_dir: Optional[str] = None,
        cancel_flag: Optional[CancelFlag] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.diffs = diffs
        self.source_root = source_root
        self.dest_root = dest_root
        self.source_device = source_device
        self.dest_device = dest_device
        self.backup_dir = backup_dir
        self.cancel_flag = cancel_flag or CancelFlag()

    def run(self) -> None:
        """执行同步操作，通过 finished 信号返回结果。"""
        try:
            # 定义一个回调：把 progress_callback 信号桥接到 Signal
            def on_progress(stage: str, phase: str, current: int, total: int, detail: str):
                if self.cancel_flag.is_set():
                    raise CancelledError("操作已被取消")
                self.progress.emit(stage, phase, current, total, detail)

            total = sum(1 for d in self.diffs if d.selected)
            self.progress.emit("execute", "transferring", 0, total, "")

            result = execute(
                self.diffs,
                self.source_root,
                self.dest_root,
                source_device=self.source_device,
                dest_device=self.dest_device,
                backup_dir=self.backup_dir,
                cancel_flag=self.cancel_flag,
                progress_callback=on_progress,
            )

            result_copy = copy.deepcopy(result)
            logger.info(
                "ExecuteWorker: 完成 — %d 成功 / %d 失败 / %d 跳过",
                result.success_count, result.failure_count, result.skip_count,
            )
            self.progress.emit("execute", "done", total, total, "")
            self.finished.emit(result_copy)

        except CancelledError:
            logger.info("ExecuteWorker: 已被取消")
            self.progress.emit("execute", "done", 0, 0, "")
        except Exception:
            logger.exception("ExecuteWorker: 异常")
            self.error.emit(f"执行失败: {logger}")
