"""test_diff_view.py — DiffView 回归测试。

覆盖 libshiboken overflow bug: Signal(int,int,int) 在文件大小 >2^31-1 时溢出。
"""
import sys

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Signal, QObject

_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)


# ============================================================================
# 回归测试: Signal(int, int, int) overflow → Slot 找不到
# ============================================================================
# 根因: PySide6 将 int 映射为 C++ signed 32-bit; selected_total_bytes()
#       sum 多选文件大小后超过 2.1GB 时 shiboken 溢出 + Slot 签名损坏。
# 修复: 第三个参数改为 object 类型, Python 原生 int 原样传递。


class TestDiffViewSignalOverflow:
    """验证 selection_changed signal 能传递 >2GB 的文件大小值。"""

    def test_signal_handles_large_byte_count(self):
        """>2GB 字节数（>2^31-1）应能通过 selection_changed signal 传递。"""
        from musicsync.ui.diff_view import DiffView

        LARGE_BYTES = 7_555_777_285  # ~7.0GB, 复现用户报错的值
        assert LARGE_BYTES > 2**31 - 1, "测试值必须超过 signed 32-bit 上限"

        dv = DiffView()

        collector = _SignalCollector()
        # 验证连接成功
        ok = dv.selection_changed.connect(collector.on_changed)
        if not ok:
            # 连接失败意味着 slot 签名不匹配（旧的 int 溢出场景）
            pytest.fail(
                "selection_changed.connect 失败 — Signal(int,int,int) 在 >2GB 值时签名损坏"
            )

        try:
            dv.selection_changed.emit(349, 227, LARGE_BYTES)
        except OverflowError as e:
            pytest.fail(
                f"selection_changed.emit 溢出: {e} — "
                "Signal 第三个参数类型不匹配，无法传递 >2GB 值"
            )

        # 验证 slot 收到了正确的值
        assert collector.received_total == 349, f"total 应为 349, 实际 {collector.received_total}"
        assert collector.received_selected == 227, f"selected 应为 227, 实际 {collector.received_selected}"
        assert collector.received_bytes == LARGE_BYTES, (
            f"estimated_bytes 应为 {LARGE_BYTES}, 实际 {collector.received_bytes}"
        )
        assert isinstance(collector.received_bytes, int), "字节数应为 Python int 类型"

    def test_signal_handles_boundary_2gb(self):
        """刚好 2^31-1（~2.15GB）的边界值应正常传递。"""
        from musicsync.ui.diff_view import DiffView

        BOUNDARY = 2**31 - 1  # 2,147,483,647 ≈ 2.0GB
        dv = DiffView()
        collector = _SignalCollector()
        ok = dv.selection_changed.connect(collector.on_changed)
        assert ok, f"边界值 {BOUNDARY} 连接失败"

        try:
            dv.selection_changed.emit(1, 1, BOUNDARY)
        except Exception as e:
            pytest.fail(f"边界值 {BOUNDARY} emit 异常: {e}")

        assert collector.received_bytes == BOUNDARY

    def test_selected_total_bytes_method(self):
        """selected_total_bytes() 应正确 sum 大量文件。"""
        from musicsync.ui.diff_view import DiffView
        from musicsync.core.models import DiffItem

        # 模拟选中多个大文件（每个 ~1GB × 10）
        large_diffs = [
            DiffItem(
                relative_path=f"big_{i}.flac",
                diff_type="new_in_dest",
                operation="copy",
                direction="[Phone] → [PC]",
                source_size=1_073_741_824,  # 1 GiB
                selected=True,
            )
            for i in range(10)
        ]

        dv = DiffView()
        dv.load_diffs(large_diffs, src_label="[Phone]", dst_label="[PC]")

        total_bytes = dv.selected_total_bytes()
        assert total_bytes == 10_737_418_240, f"10GB sum 应为 10737418240, 实际 {total_bytes}"
        assert total_bytes > 2**31 - 1, "10GiB 远超 signed 32-bit 上限"


class _SignalCollector(QObject):
    """收集 selection_changed signal 的参数。"""

    def __init__(self):
        super().__init__()
        self.received_total = None
        self.received_selected = None
        self.received_bytes = None

    def on_changed(self, total, selected, estimated_bytes):
        self.received_total = total
        self.received_selected = selected
        self.received_bytes = estimated_bytes
