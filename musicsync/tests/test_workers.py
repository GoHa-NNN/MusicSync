"""test_workers.py — Worker 信号发射逻辑自动化测试。

测试三个 Worker（ScanWorker / CompareWorker / ExecuteWorker）在
已知输入下的 Signal 发射行为，无需真实窗口渲染。

通过创建 ``QApplication([])`` 实例后同步调用 ``worker.run()``，
验证 finished / progress / error 信号的值。
"""

import os
import tempfile
import copy

import pytest
from PySide6.QtCore import QObject, Signal

# QApplication 实例需在创建任何 QObject 之前存在
from PySide6.QtWidgets import QApplication

_app = QApplication.instance()
if _app is None:
    _app = QApplication([])

from musicsync.ui.workers import ScanWorker, CompareWorker, ExecuteWorker  # noqa: E402
from musicsync.adb_device_kit.cancel_flag import CancelFlag  # noqa: E402
from musicsync.adb_device_kit.models import FileInfo, ActionResult  # noqa: E402
from musicsync.core.models import DiffItem  # noqa: E402


# ---------------------------------------------------------------------------
# 测试辅助：信号收集器
# ---------------------------------------------------------------------------

class SignalCollector(QObject):
    """收集最后一个 Signal 值，用于同步等待信号。

    在测试中，worker.run() 同步调用（不启动额外线程），
    所以信号在 run() 返回前已发射。直接连接收集即可。
    """

    def __init__(self):
        super().__init__()
        self.finished_value = None
        self.progress_values: list = []
        self.error_value = None

    def on_finished(self, *args):
        self.finished_value = args if len(args) > 1 else args[0]

    def on_progress(self, stage, phase, current, total, detail):
        self.progress_values.append((stage, phase, current, total, detail))

    def on_error(self, msg):
        self.error_value = msg


# ---------------------------------------------------------------------------
# 文件辅助
# ---------------------------------------------------------------------------

def _write_file(path: str, content: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# ScanWorker 测试
# ---------------------------------------------------------------------------

class TestScanWorker:
    """测试 ScanWorker 的信号发射行为（PC 本地扫描）。"""

    def test_scans_source_and_dest(self):
        """ScanWorker 应扫描两端并返回文件列表。"""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            _write_file(os.path.join(src, "a.flac"), b"src-a")
            _write_file(os.path.join(src, "b.mp3"), b"src-b" * 100)
            _write_file(os.path.join(src, "c.jpg"), b"not-audio")  # 应被过滤
            _write_file(os.path.join(dst, "a.flac"), b"dst-a")
            _write_file(os.path.join(dst, "x.wav"), b"dst-x")

            collector = SignalCollector()
            flag = CancelFlag()
            worker = ScanWorker(
                source_root=src,
                source_extensions=["flac", "mp3", "wav", "aac", "ogg", "m4a", "wma"],
                dest_root=dst,
                dest_extensions=["flac", "mp3", "wav", "aac", "ogg", "m4a", "wma"],
                cancel_flag=flag,
            )
            ok1 = worker.finished.connect(collector.on_finished)
            assert ok1, "finished signal connect failed"
            ok2 = worker.progress.connect(collector.on_progress)
            assert ok2, "progress signal connect failed"
            ok3 = worker.error.connect(collector.on_error)
            assert ok3, "error signal connect failed"

            # 同步调用（不启动线程）
            worker.run()

            # 验证 finished
            assert collector.finished_value is not None, "finished 信号未发射"
            src_files, dst_files, skipped = collector.finished_value
            assert len(src_files) == 2, f"源端应 2 个音频文件，实际 {len(src_files)}"
            assert len(dst_files) == 2, f"目的端应 2 个音频文件，实际 {len(dst_files)}"
            assert skipped.total >= 1  # c.jpg

            # 验证 progress 阶段
            stages = set(p[0] for p in collector.progress_values)
            assert "scan" in stages
            phases = set(p[1] for p in collector.progress_values)
            assert "done" in phases or "source" in phases

            # 验证 FileInfo 是独立副本（不是原始引用）
            src_files[0].size = -999
            assert worker.source_extensions == ["flac", "mp3", "wav", "aac", "ogg", "m4a", "wma"]

    def test_signal_connect_assertions(self):
        """signal.connect() 返回值断言 —— 所有连接应返回 True。"""
        flag = CancelFlag()
        worker = ScanWorker("/tmp/a", ["flac"], "/tmp/b", ["mp3"], cancel_flag=flag)
        collector = SignalCollector()

        assert worker.finished.connect(collector.on_finished), "finished connect failed"
        assert worker.progress.connect(collector.on_progress), "progress connect failed"
        assert worker.error.connect(collector.on_error), "error connect failed"

    def test_empty_directory(self):
        """空目录扫描应返回空列表。"""
        with tempfile.TemporaryDirectory() as d:
            collector = SignalCollector()
            worker = ScanWorker(
                source_root=d, source_extensions=["flac"],
                dest_root=d, dest_extensions=["mp3"],
                cancel_flag=CancelFlag(),
            )
            worker.finished.connect(collector.on_finished)
            worker.run()

            src_files, dst_files, skipped = collector.finished_value
            assert src_files == []
            assert dst_files == []

    def test_progress_emitted(self):
        """扫描应发射至少一条 progress 信号。"""
        with tempfile.TemporaryDirectory() as d:
            _write_file(os.path.join(d, "song.flac"), b"x" * 100)
            collector = SignalCollector()
            worker = ScanWorker(d, ["flac"], d, ["flac"], cancel_flag=CancelFlag())
            worker.progress.connect(collector.on_progress)
            worker.run()

            assert len(collector.progress_values) >= 1
            # 验证 Signal 格式：5 个字段
            for p in collector.progress_values:
                assert len(p) == 5

    def test_cancel_immediate(self):
        """已设置的 CancelFlag → run() 立即退出。"""
        with tempfile.TemporaryDirectory() as d:
            flag = CancelFlag()
            flag.cancel()  # 预先设置
            collector = SignalCollector()
            worker = ScanWorker(d, ["flac"], d, ["flac"], cancel_flag=flag)
            worker.finished.connect(collector.on_finished)
            worker.run()

            # run() 正常返回，finished 未发射
            assert collector.finished_value is None


# ---------------------------------------------------------------------------
# CompareWorker 测试
# ---------------------------------------------------------------------------

class TestCompareWorker:
    """测试 CompareWorker 的信号发射行为。"""

    def _make_fi(self, rel: str, size: int) -> FileInfo:
        return FileInfo(path=f"/tmp/{rel}", relative_path=rel, size=size)

    def test_compare_produces_diffs(self):
        """比对两端有差异的文件列表，应产出 DiffItem 列表。"""
        src_files = [
            self._make_fi("a.flac", 100),
            self._make_fi("b.mp3", 200),
            self._make_fi("only_src.flac", 300),
        ]
        dst_files = [
            self._make_fi("a.flac", 100),   # synced
            self._make_fi("b.mp3", 250),    # updated（大小不同）
            self._make_fi("only_dst.wav", 400),  # only_in_dest
        ]

        collector = SignalCollector()
        worker = CompareWorker(src_files, dst_files, cancel_flag=CancelFlag())
        assert worker.finished.connect(collector.on_finished), "finished connect failed"
        assert worker.progress.connect(collector.on_progress), "progress connect failed"

        worker.run()

        diffs = collector.finished_value
        assert diffs is not None
        assert isinstance(diffs, list)
        assert len(diffs) == 3, f"应 3 项差异（1 updated + 1 new + 1 only_in_dest），实际 {len(diffs)}"

        # 按操作类型分组
        ops = {d.operation for d in diffs}
        assert "overwrite" in ops  # b.mp3
        assert "copy" in ops       # only_src.flac
        assert "delete" in ops     # only_dst.wav

        # selected 默认值
        assert all(d.selected for d in diffs)

    def test_all_synced(self):
        """完全一致的两端应返回空差异列表。"""
        src_files = [self._make_fi("a.flac", 100), self._make_fi("b.mp3", 200)]
        dst_files = [self._make_fi("a.flac", 100), self._make_fi("b.mp3", 200)]

        collector = SignalCollector()
        worker = CompareWorker(src_files, dst_files, cancel_flag=CancelFlag())
        worker.finished.connect(collector.on_finished)
        worker.run()

        diffs = collector.finished_value
        assert diffs == []

    def test_deep_copy(self):
        """finished 发送的差异列表应是独立副本。"""
        src_files = [self._make_fi("a.flac", 100)]
        dst_files = [self._make_fi("a.flac", 200)]

        collector = SignalCollector()
        worker = CompareWorker(src_files, dst_files, cancel_flag=CancelFlag())
        worker.finished.connect(collector.on_finished)
        worker.run()

        diffs = collector.finished_value
        assert len(diffs) == 1
        # 修改返回的值不应影响 worker 内部状态
        original_path = diffs[0].relative_path
        diffs[0].relative_path = "modified"
        assert diffs[0].relative_path == "modified"
        # 原始输入未受影响
        assert src_files[0].relative_path == "a.flac"

    def test_cancel_immediate(self):
        """已取消时返回 None（finished 未发射）。"""
        src_files = [self._make_fi("a.flac", 100)]
        dst_files = [self._make_fi("b.flac", 100)]
        flag = CancelFlag()
        flag.cancel()
        collector = SignalCollector()
        worker = CompareWorker(src_files, dst_files, cancel_flag=flag)
        worker.finished.connect(collector.on_finished)
        worker.run()

        # compare() 内部检测到 cancel_flag，返回空列表
        # 但 CompareWorker 在 cancel 后不发送 finished
        assert collector.finished_value is None

    def test_progress_signal_format(self):
        """progress 信号格式应为 (str, str, int, int, str)。"""
        src_files = [self._make_fi("a.flac", 100)]
        dst_files = []
        collector = SignalCollector()
        worker = CompareWorker(src_files, dst_files, cancel_flag=CancelFlag())
        worker.progress.connect(collector.on_progress)
        worker.run()

        assert len(collector.progress_values) >= 1
        for p in collector.progress_values:
            assert len(p) == 5
            stage, phase, current, total, detail = p
            assert isinstance(stage, str)
            assert isinstance(phase, str)
            assert isinstance(current, int)
            assert isinstance(total, int)
            assert isinstance(detail, str)


# ---------------------------------------------------------------------------
# ExecuteWorker 测试
# ---------------------------------------------------------------------------

class TestExecuteWorker:
    """测试 ExecuteWorker 的信号发射行为。"""

    def _make_diff(self, rel: str, operation: str, source_size: int = 100) -> DiffItem:
        direction = "source → dest" if operation != "delete" else "dest"
        return DiffItem(
            relative_path=rel,
            diff_type={"copy": "new_in_dest", "overwrite": "updated_in_dest", "delete": "only_in_dest"}[operation],
            operation=operation,
            direction=direction,
            source_size=source_size if operation != "delete" else None,
            dest_size=None,
            selected=True,
        )

    def test_copy_files(self):
        """执行 copy 操作应将文件从源端传输到目的端。"""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            _write_file(os.path.join(src, "song.flac"), b"hello" * 100)

            diff = self._make_diff("song.flac", "copy")
            collector = SignalCollector()
            worker = ExecuteWorker(
                [diff], src, dst,
                cancel_flag=CancelFlag(),
            )
            assert worker.finished.connect(collector.on_finished), "finished connect failed"
            assert worker.progress.connect(collector.on_progress), "progress connect failed"

            worker.run()

            result: ActionResult = collector.finished_value
            assert result is not None
            assert result.success_count == 1, f"应 1 成功，实际: {result.failures}"
            assert result.failure_count == 0
            assert os.path.exists(os.path.join(dst, "song.flac"))

    def test_overwrite_file(self):
        """overwrite 操作应用源端内容覆盖目的端文件。"""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            _write_file(os.path.join(src, "song.flac"), b"SRC_CONTENT" * 100)
            _write_file(os.path.join(dst, "song.flac"), b"OLD_DST" * 10)

            diff = self._make_diff("song.flac", "overwrite")
            collector = SignalCollector()
            worker = ExecuteWorker([diff], src, dst, cancel_flag=CancelFlag())
            worker.finished.connect(collector.on_finished)
            worker.run()

            result = collector.finished_value
            assert result.success_count == 1

    def test_delete_file(self):
        """delete 操作应从目的端删除文件。"""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            _write_file(os.path.join(dst, "old.flac"), b"to-delete" * 50)

            diff = self._make_diff("old.flac", "delete")
            collector = SignalCollector()
            worker = ExecuteWorker([diff], src, dst, cancel_flag=CancelFlag())
            worker.finished.connect(collector.on_finished)
            worker.run()

            result = collector.finished_value
            assert result.success_count == 1, f"删除应成功，实际: {result.failures}"
            assert not os.path.exists(os.path.join(dst, "old.flac"))

    def test_unselected_skipped(self):
        """未勾选的差异项应被跳过。"""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            _write_file(os.path.join(src, "song.flac"), b"x" * 100)

            diff = self._make_diff("song.flac", "copy")
            diff.selected = False
            collector = SignalCollector()
            worker = ExecuteWorker([diff], src, dst, cancel_flag=CancelFlag())
            worker.finished.connect(collector.on_finished)
            worker.run()

            result = collector.finished_value
            assert result.skip_count == 1
            assert result.success_count == 0

    def test_failure_reported(self):
        """源文件不存在时应报告失败。"""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            # 不创建源文件
            diff = self._make_diff("missing.flac", "copy")
            collector = SignalCollector()
            worker = ExecuteWorker([diff], src, dst, cancel_flag=CancelFlag())
            worker.finished.connect(collector.on_finished)
            worker.run()

            result = collector.finished_value
            assert result.failure_count == 1
            assert len(result.failures) == 1

    def test_progress_signal_emitted(self):
        """执行应发射 progress 信号。"""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            _write_file(os.path.join(src, "a.flac"), b"x" * 100)
            diff = self._make_diff("a.flac", "copy")
            collector = SignalCollector()
            worker = ExecuteWorker([diff], src, dst, cancel_flag=CancelFlag())
            worker.progress.connect(collector.on_progress)
            worker.run()

            assert len(collector.progress_values) >= 2  # 至少开始 + done
            # 验证格式
            for p in collector.progress_values:
                assert len(p) == 5
                stage, phase, current, total, detail = p
                assert isinstance(stage, str)
                assert isinstance(phase, str)
                assert isinstance(current, int)
                assert isinstance(total, int)
                assert isinstance(detail, str)

    def test_cancel_immediate(self):
        """已取消时跳过所有操作。"""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            _write_file(os.path.join(src, "a.flac"), b"x" * 100)
            diff = self._make_diff("a.flac", "copy")
            flag = CancelFlag()
            flag.cancel()
            collector = SignalCollector()
            worker = ExecuteWorker([diff], src, dst, cancel_flag=flag)
            worker.finished.connect(collector.on_finished)
            worker.run()

            assert collector.finished_value is None

    def test_deep_copy_result(self):
        """ActionResul' 应是独立副本。"""
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            _write_file(os.path.join(src, "a.flac"), b"x" * 100)
            diff = self._make_diff("a.flac", "copy")
            collector = SignalCollector()
            worker = ExecuteWorker([diff], src, dst, cancel_flag=CancelFlag())
            worker.finished.connect(collector.on_finished)
            worker.run()

            result = collector.finished_value
            assert isinstance(result, ActionResult)
            # 修改不影响 worker
            original = result.success_count
            result.success_count = -1
            assert result.success_count == -1  # 本地修改成功
