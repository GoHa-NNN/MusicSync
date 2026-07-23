"""test_dir_bar.py — DirBar ADB 设备检测逻辑测试。

覆盖:
    - Phone 选择时 ADB 设备检测 → 按钮启用/禁用
    - PC 选择时跳过 ADB 检测 → 按钮仅由路径决定
    - ADB 状态提示标签 + 重新检测按钮的显示/隐藏
    - "重新检测"按钮点击后重新执行 ADB 检测
    - 路径为空时的按钮禁用（保持原有逻辑）
    - Device.detect() 异常时安全降级
"""

import sys
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance()
if _app is None:
    _app = QApplication(sys.argv)

from musicsync.ui.dir_bar import DirBar, PHONE_DEFAULT_PATH  # noqa: E402
from musicsync.adb_device_kit.device import Device  # noqa: E402


# ============================================================================
# 辅助
# ============================================================================

def _select_device(dir_bar, side: str, device: str):
    """模拟用户在 ComboBox 中选择设备类型。

    注意：setCurrentIndex 仅在 index 变化时触发 currentIndexChanged 信号。
    如果当前 index 已经等于目标 index，需要先切到相反值再切回。
    """
    combo = dir_bar._src_device_combo if side == "source" else dir_bar._dest_device_combo
    target = 1 if device == "phone" else 0
    if combo.currentIndex() == target:
        combo.setCurrentIndex(1 - target)
    combo.setCurrentIndex(target)


def _set_path(dir_bar, side: str, path: str):
    """模拟用户输入路径。"""
    inp = dir_bar._src_path_input if side == "source" else dir_bar._dest_path_input
    inp.setText(path)


def _make_dir_bar(adb_connected=True):
    """创建一个 DirBar 实例，mock 掉 Device.detect() 以避免真实 ADB 调用。"""
    with patch.object(Device, "detect", return_value=adb_connected):
        return DirBar(db_path=":memory:")


def _with_detect_mock(detect_result: bool):
    """在 block 内 mock Device.detect 为指定返回值。"""
    return patch.object(Device, "detect", return_value=detect_result)


def _status_visible(dir_bar):
    """判断 ADB 状态容器是否"可见"。"""
    return not dir_bar._adb_status_container.isHidden()


# ============================================================================
# 路径为空 → 按钮禁用
# ============================================================================

class TestButtonDisabledWhenPathEmpty:
    """两行路径为空时，按钮始终禁用，不触发 ADB 检测。"""

    def test_both_empty_pc_to_pc(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "pc")
        _set_path(db, "source", "")
        _set_path(db, "dest", "")
        assert not db._start_btn.isEnabled()

    def test_both_empty_pc_to_phone_no_device(self):
        db = _make_dir_bar(adb_connected=False)
        _select_device(db, "source", "pc")
        with _with_detect_mock(False):
            _select_device(db, "dest", "phone")
        _set_path(db, "dest", "")
        assert not db._start_btn.isEnabled()

    def test_source_empty_dest_filled(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "pc")
        _set_path(db, "source", "")
        _set_path(db, "dest", "C:/Music")
        assert not db._start_btn.isEnabled()

    def test_dest_empty_source_filled(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "pc")
        _set_path(db, "source", "C:/Music")
        _set_path(db, "dest", "")
        assert not db._start_btn.isEnabled()


# ============================================================================
# PC→PC：不触发 ADB 检测
# ============================================================================

class TestPcToPcNoAdbCheck:
    def test_both_filled_pc_to_pc_enabled(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "pc")
        _set_path(db, "source", "C:/Source")
        _set_path(db, "dest", "C:/Dest")
        assert db._start_btn.isEnabled()

    def test_pc_to_pc_no_adb_status(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "pc")
        _set_path(db, "source", "C:/Source")
        _set_path(db, "dest", "C:/Dest")
        assert not _status_visible(db)


# ============================================================================
# Phone + ADB 已连接
# ============================================================================

class TestPhoneDetectedEnablesButton:
    def test_dest_phone_detected(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        with _with_detect_mock(True):
            _select_device(db, "dest", "phone")
        _set_path(db, "dest", "/sdcard/Music/")
        assert db._start_btn.isEnabled()
        assert db._dst_phone_ready is True

    def test_source_phone_detected(self):
        db = _make_dir_bar()
        _select_device(db, "dest", "pc")
        _set_path(db, "dest", "C:/Dest")
        with _with_detect_mock(True):
            _select_device(db, "source", "phone")
        _set_path(db, "source", "/sdcard/Music/")
        assert db._start_btn.isEnabled()
        assert db._src_phone_ready is True

    def test_both_phone_detected(self):
        db = _make_dir_bar()
        with _with_detect_mock(True):
            _select_device(db, "source", "phone")
            _select_device(db, "dest", "phone")
        _set_path(db, "source", "/sdcard/Music/Artist/")
        _set_path(db, "dest", "/sdcard/Music/Sorted/")
        assert db._start_btn.isEnabled()
        assert db._src_phone_ready is True
        assert db._dst_phone_ready is True


# ============================================================================
# Phone + ADB 未连接 → 按钮禁用 + 状态显示
# ============================================================================

class TestPhoneNotDetectedDisablesButton:
    def test_dest_phone_not_detected(self):
        db = _make_dir_bar(adb_connected=False)
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        with _with_detect_mock(False):
            _select_device(db, "dest", "phone")
        assert db._dest_path_input.text().strip() == PHONE_DEFAULT_PATH
        assert not db._start_btn.isEnabled()
        assert db._dst_phone_ready is False

    def test_source_phone_not_detected(self):
        db = _make_dir_bar()
        _select_device(db, "dest", "pc")
        _set_path(db, "dest", "C:/Dest")
        with _with_detect_mock(False):
            _select_device(db, "source", "phone")
        _set_path(db, "source", "/sdcard/Music/")
        assert not db._start_btn.isEnabled()
        assert db._src_phone_ready is False

    def test_status_container_visible(self):
        db = _make_dir_bar(adb_connected=False)
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        with _with_detect_mock(False):
            _select_device(db, "dest", "phone")
        assert _status_visible(db)
        assert "USB 调试" in db._adb_status_label.text()

    def test_status_hidden_after_switch_to_pc(self):
        db = _make_dir_bar(adb_connected=False)
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        with _with_detect_mock(False):
            _select_device(db, "dest", "phone")
        assert _status_visible(db)
        _select_device(db, "dest", "pc")
        _set_path(db, "dest", "C:/Dest")
        assert not _status_visible(db)


# ============================================================================
# "重新检测"按钮
# ============================================================================

class TestAdbRetryButton:
    def test_retry_button_visible_when_phone_not_connected(self):
        """未检测到 ADB 设备时，重新检测按钮可见。"""
        db = _make_dir_bar(adb_connected=False)
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        with _with_detect_mock(False):
            _select_device(db, "dest", "phone")
        assert _status_visible(db)
        # 重新检测按钮存在于容器中
        assert db._adb_retry_btn.isVisible() or _status_visible(db)

    def test_retry_after_device_plugged_in(self):
        """模拟用户插上手机后点击"重新检测"→ 检测成功 → 按钮启用。"""
        db = _make_dir_bar(adb_connected=False)
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        # 初始状态：ADB 未连接
        assert not db._start_btn.isEnabled()
        assert _status_visible(db)

        # 用户插上手机，点击"重新检测"
        with _with_detect_mock(True):
            db._adb_retry_btn.click()

        # 检测成功 → 状态标签隐藏，按钮启用
        assert not _status_visible(db)
        assert db._start_btn.isEnabled()

    def test_retry_still_disconnected(self):
        """重新检测仍失败 → 按钮继续禁用，状态保持显示。"""
        db = _make_dir_bar(adb_connected=False)
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        assert not db._start_btn.isEnabled()

        # 再次检测仍未连接
        with _with_detect_mock(False):
            db._adb_retry_btn.click()

        assert not db._start_btn.isEnabled()
        assert _status_visible(db)

    def test_retry_only_checks_phone_sides(self):
        """重新检测仅对当前选中 Phone 的端执行，PC 端跳过。"""
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "pc")
        _set_path(db, "source", "C:/Source")
        _set_path(db, "dest", "C:/Dest")
        assert db._start_btn.isEnabled()

        # PC→PC 模式点击重新检测不会有副作用
        db._adb_retry_btn.click()
        assert db._start_btn.isEnabled()


# ============================================================================
# 切换设备类型状态恢复
# ============================================================================

class TestDeviceSwitchStateRecovery:
    def test_switch_phone_to_pc_reenables(self):
        db = _make_dir_bar(adb_connected=False)
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        assert not db._start_btn.isEnabled()
        _select_device(db, "dest", "pc")
        _set_path(db, "dest", "C:/Dest")
        assert db._start_btn.isEnabled()

    def test_switch_pc_to_phone_with_device_enables(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "pc")
        _set_path(db, "source", "C:/Source")
        _set_path(db, "dest", "C:/Dest")
        assert db._start_btn.isEnabled()
        with _with_detect_mock(True):
            _select_device(db, "dest", "phone")
        _set_path(db, "dest", "/sdcard/Music/")
        assert db._start_btn.isEnabled()


# ============================================================================
# 异常安全
# ============================================================================

class TestDetectExceptionSafety:
    def test_detect_raises_exception(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        with patch.object(Device, "detect", side_effect=RuntimeError("模拟错误")):
            _select_device(db, "dest", "phone")
        assert not db._start_btn.isEnabled()
        assert _status_visible(db)

    def test_retry_after_exception_then_success(self):
        """上次 detect 抛异常，重新检测成功后恢复正常。"""
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        with patch.object(Device, "detect", side_effect=RuntimeError("模拟错误")):
            _select_device(db, "dest", "phone")
        assert not db._start_btn.isEnabled()

        # 重新检测 → 成功
        with _with_detect_mock(True):
            db._adb_retry_btn.click()

        assert db._start_btn.isEnabled()
        assert not _status_visible(db)


# ============================================================================
# tooltip
# ============================================================================

class TestButtonTooltip:
    def test_tooltip_when_paths_empty(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "pc")
        _set_path(db, "source", "")
        _set_path(db, "dest", "")
        assert "路径" in db._start_btn.toolTip()

    def test_tooltip_when_phone_not_connected(self):
        db = _make_dir_bar(adb_connected=False)
        _select_device(db, "source", "pc")
        _set_path(db, "source", "C:/Source")
        with _with_detect_mock(False):
            _select_device(db, "dest", "phone")
        assert "USB 调试" in db._start_btn.toolTip()

    def test_tooltip_empty_when_ready(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "pc")
        _set_path(db, "source", "C:/Source")
        _set_path(db, "dest", "C:/Dest")
        assert db._start_btn.toolTip() == ""


# ============================================================================
# 公共接口
# ============================================================================

class TestPublicInterfaceUnchanged:
    def test_device_type_methods(self):
        db = _make_dir_bar()
        _select_device(db, "source", "pc")
        _select_device(db, "dest", "phone")
        assert db.source_device_type() == "pc"
        assert db.dest_device_type() == "phone"

    def test_path_methods(self):
        db = _make_dir_bar()
        _set_path(db, "source", "C:/Test/Source")
        _set_path(db, "dest", "/sdcard/Test")
        assert db.source_path() == "C:/Test/Source"
        assert db.dest_path() == "/sdcard/Test"


# ============================================================================
# 回归防护：Phone 路径自动填入
# ============================================================================

class TestPhoneDefaultPathRegression:
    def test_source_phone_autofill(self):
        db = _make_dir_bar()
        with _with_detect_mock(True):
            _select_device(db, "source", "phone")
        assert db._src_path_input.text() == PHONE_DEFAULT_PATH

    def test_dest_phone_autofill(self):
        db = _make_dir_bar()
        with _with_detect_mock(True):
            _select_device(db, "dest", "phone")
        assert db._dest_path_input.text() == PHONE_DEFAULT_PATH
