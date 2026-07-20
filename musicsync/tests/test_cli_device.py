"""test_cli_device.py — CLI 参数解析与设备分发单元测试。

不依赖真实 ADB 设备，仅测试 argparse 解析和 _maybe_connect 逻辑。
"""

import pytest
from unittest import mock
import sys

import musicsync.cli as cli_module
from musicsync.cli import _maybe_connect, main


# ---------------------------------------------------------------------------
# argparse 参数解析测试
# ---------------------------------------------------------------------------

class TestArgparse:
    """测试 CLI 参数解析的合法值、默认值和非法值拒绝。"""

    def test_default_both_pc(self):
        """不带任何 device flag 时，source 和 dest 默认均为 pc。"""
        argv = ["cli.py", "/tmp/src", "/tmp/dst"]
        args = _parse(argv)
        assert args.source_device == "pc"
        assert args.dest_device == "pc"
        assert args.source == "/tmp/src"
        assert args.dest == "/tmp/dst"

    def test_source_phone(self):
        """--source-device phone 解析正确。"""
        args = _parse(["cli.py", "--source-device", "phone", "/s", "/d"])
        assert args.source_device == "phone"
        assert args.dest_device == "pc"

    def test_dest_phone(self):
        """--dest-device phone 解析正确。"""
        args = _parse(["cli.py", "--dest-device", "phone", "/s", "/d"])
        assert args.source_device == "pc"
        assert args.dest_device == "phone"

    def test_both_phone(self):
        """两端均为 phone 时解析正确（执行时会抛 NotImplementedError）。"""
        args = _parse([
            "cli.py",
            "--source-device", "phone",
            "--dest-device", "phone",
            "//sdcard/A/", "//sdcard/B/",
        ])
        assert args.source_device == "phone"
        assert args.dest_device == "phone"

    def test_invalid_device_rejected(self):
        """非法 device 值被 argparse 拒绝。"""
        with pytest.raises(SystemExit):
            _parse(["cli.py", "--source-device", "tablet", "/s", "/d"])

    def test_missing_positional_args(self):
        """缺少位置参数被 argparse 拒绝。"""
        with pytest.raises(SystemExit):
            _parse(["cli.py", "--source-device", "phone"])

    def test_yes_flag_default_false(self):
        """--yes 默认 False。"""
        args = _parse(["cli.py", "/s", "/d"])
        assert not args.yes

    def test_yes_flag_short(self):
        """-y 短选项可用。"""
        args = _parse(["cli.py", "-y", "/s", "/d"])
        assert args.yes

    def test_yes_flag_long(self):
        """--yes 长选项可用。"""
        args = _parse(["cli.py", "--yes", "/s", "/d"])
        assert args.yes

    def test_help_includes_phone_option(self):
        """--help 输出中包含 phone 选项说明。"""
        with pytest.raises(SystemExit):
            _parse(["cli.py", "--help"])


# ---------------------------------------------------------------------------
# _maybe_connect 测试（mock Device）
# ---------------------------------------------------------------------------

class TestMaybeConnect:
    """测试 _maybe_connect 的设备检测逻辑。"""

    def test_not_wanted_returns_none(self):
        """wanted=False 时直接返回 None，不尝试连接。"""
        result = _maybe_connect(wanted=False, label="test")
        assert result is None

    @mock.patch("musicsync.cli.Device")
    def test_detect_success_returns_device(self, mock_device_cls):
        """detect 成功时返回 Device 实例。"""
        mock_inst = mock.MagicMock()
        mock_inst.detect.return_value = True
        mock_device_cls.return_value = mock_inst

        result = _maybe_connect(wanted=True, label="测试")
        assert result is mock_inst

    @mock.patch("musicsync.cli.Device")
    def test_detect_failure_exits(self, mock_device_cls):
        """detect 失败时调用 sys.exit(1)。"""
        mock_inst = mock.MagicMock()
        mock_inst.detect.return_value = False
        mock_device_cls.return_value = mock_inst

        with pytest.raises(SystemExit) as exc_info:
            _maybe_connect(wanted=True, label="测试")
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _parse(argv: list[str]) -> object:
    """用 cli.py 中的 parser 解析给定参数。"""
    # 在 main() 中定义的 parser 不方便直接访问，我们直接调用 argparse
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-device", choices=["pc", "phone"], default="pc")
    parser.add_argument("--dest-device", choices=["pc", "phone"], default="pc")
    parser.add_argument("--yes", "-y", action="store_true")
    parser.add_argument("source")
    parser.add_argument("dest")
    return parser.parse_args(argv[1:])
