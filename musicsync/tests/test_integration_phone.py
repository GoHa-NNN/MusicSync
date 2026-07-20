"""test_integration_phone.py — PC→Phone + Phone→PC 实机集成测试。

需要真实 ADB 设备连接。使用隔离的临时目录，不动用户真实数据。

标记: Integration or Real
"""

import os
import subprocess
import tempfile
import pytest

# 仅在导入成功时注册测试
try:
    from musicsync.adb_device_kit.device import Device
    from musicsync.core.sync_engine import scan, compare
    from musicsync.core.executor import execute
    from musicsync.adb_device_kit.filter_utils import DEFAULT_AUDIO_EXTENSIONS
    from musicsync.adb_device_kit.cancel_flag import CancelFlag
    from musicsync.core.models import DiffItem
    from musicsync.adb_device_kit.executor_helpers import safe_delete_remote

    _HAS_DEVICE = Device("adb").detect()
except Exception:
    _HAS_DEVICE = False


# ---------------------------------------------------------------------------
# 隔离测试目录常量
# ---------------------------------------------------------------------------

PHONE_TEST_DIR = "//sdcard/MusicSync_test/"
PC_TEMP_PREFIX = os.path.join(tempfile.gettempdir(), "ms_integration_")


def _setup_pc_dirs():
    """创建隔离的 PC 端源/目的目录。"""
    src = tempfile.mkdtemp(prefix=PC_TEMP_PREFIX + "src_")
    dst = tempfile.mkdtemp(prefix=PC_TEMP_PREFIX + "dst_")
    return src, dst


def _cleanup_pc(*dirs):
    """清理 PC 端临时目录。"""
    import shutil
    for d in dirs:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)


def _cleanup_phone(device, *relative_paths):
    """删除手机上指定相对路径的文件，并清理空目录。"""
    for rel in relative_paths:
        full = PHONE_TEST_DIR.rstrip("/") + "/" + rel.lstrip("/")
        device.delete(full)


def _write_file(path: str, content: bytes):
    """兼容 str 类型的 write_bytes（os.path.join 返回 str 而非 Path）。"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 真实设备 fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def device():
    """模块级 fixture：返回一个已连接的 Device 实例。"""
    if not _HAS_DEVICE:
        pytest.skip("需要真实 ADB 设备")
    d = Device("adb")
    # 清理上次测试残留
    for f in d.list_files(PHONE_TEST_DIR) or []:
        d.delete(f)
    return d


# ---------------------------------------------------------------------------
# PC→Phone 集成测试
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_DEVICE, reason="需要真实 ADB 设备")
class TestPcToPhoneIntegration:
    """PC→Phone 全链路：copy → re-scan 0 diff → overwrite → delete → re-scan 0 diff。"""

    def test_full_lifecycle_copy_re_scan_overwrite_delete(self, device):
        """完整生命周期：创建→同步→验证→覆盖→删除→验证。"""
        src_dir, dst_dir = _setup_pc_dirs()
        try:
            # ── 1. 创建 PC 源端文件 ──
            _write_file(os.path.join(src_dir, "a.flac"), b"phone-int-1")
            _write_file(os.path.join(src_dir, "nested", "b.flac"), b"phone-int-222")

            # ── 2. PC→Phone sync（copy）──
            src_files, _ = scan(
                src_dir, DEFAULT_AUDIO_EXTENSIONS, device=None, cancel_flag=None,
            )
            dest_files_before, _ = scan(
                PHONE_TEST_DIR, DEFAULT_AUDIO_EXTENSIONS, device=device, cancel_flag=None,
            )
            diffs = compare(src_files, dest_files_before)
            assert len(diffs) == 2
            assert all(d.operation in ("copy", "overwrite") for d in diffs)

            result = execute(
                diffs, src_dir, PHONE_TEST_DIR,
                dest_device=device,
            )
            assert result.success_count == 2, f"Failures: {result.failures}"
            assert result.failure_count == 0

            # ── 3. 再比对 → 0 差异 ──
            src_files2, _ = scan(
                src_dir, DEFAULT_AUDIO_EXTENSIONS, device=None, cancel_flag=None,
            )
            dest_files2, _ = scan(
                PHONE_TEST_DIR, DEFAULT_AUDIO_EXTENSIONS, device=device, cancel_flag=None,
            )
            diffs2 = compare(src_files2, dest_files2)
            assert len(diffs2) == 0, (
                f"再比对应为 0 差异，实际 {len(diffs2)}: "
                f"{[(d.relative_path, d.diff_type) for d in diffs2]}"
            )

            # ── 4. 修改源端 → overwrite ──
            _write_file(os.path.join(src_dir, "a.flac"), b"UPDATED-LARGER-CONTENT")

            src_files3, _ = scan(
                src_dir, DEFAULT_AUDIO_EXTENSIONS, device=None, cancel_flag=None,
            )
            dest_files3, _ = scan(
                PHONE_TEST_DIR, DEFAULT_AUDIO_EXTENSIONS, device=device, cancel_flag=None,
            )
            diffs3 = compare(src_files3, dest_files3)
            assert len(diffs3) == 1
            assert diffs3[0].diff_type == "updated_in_dest"

            result3 = execute(
                diffs3, src_dir, PHONE_TEST_DIR,
                dest_device=device,
            )
            assert result3.success_count == 1

            # ── 5. 删除源端 → phone 端删除 ──
            os.unlink(os.path.join(src_dir, "a.flac"))

            src_files4, _ = scan(
                src_dir, DEFAULT_AUDIO_EXTENSIONS, device=None, cancel_flag=None,
            )
            dest_files4, _ = scan(
                PHONE_TEST_DIR, DEFAULT_AUDIO_EXTENSIONS, device=device, cancel_flag=None,
            )
            diffs4 = compare(src_files4, dest_files4)
            assert len(diffs4) == 1
            assert diffs4[0].operation == "delete"

            result4 = execute(
                diffs4, src_dir, PHONE_TEST_DIR,
                dest_device=device,
            )
            assert result4.success_count == 1

            # ── 6. 最终再比对 → 0 差异 ──
            src_files5, _ = scan(
                src_dir, DEFAULT_AUDIO_EXTENSIONS, device=None, cancel_flag=None,
            )
            dest_files5, _ = scan(
                PHONE_TEST_DIR, DEFAULT_AUDIO_EXTENSIONS, device=device, cancel_flag=None,
            )
            diffs5 = compare(src_files5, dest_files5)
            assert len(diffs5) == 0

        finally:
            _cleanup_pc(src_dir, dst_dir)
            # 清理手机端残留
            for f in device.list_files(PHONE_TEST_DIR) or []:
                device.delete(f)

    def test_cancel_mid_execution(self, device):
        """cancel_flag 在 PC→Phone 中应被检查。"""
        src_dir, dst_dir = _setup_pc_dirs()
        try:
            _write_file(os.path.join(src_dir, "x.flac"), b"short")
            flag = CancelFlag()
            flag.cancel()  # 执行前就取消

            diffs = [DiffItem(
                relative_path="x.flac",
                diff_type="new_in_dest",
                operation="copy",
                direction="source → dest",
                source_size=5,
                dest_size=None,
                selected=True,
            )]
            result = execute(
                diffs, src_dir, PHONE_TEST_DIR,
                dest_device=device,
                cancel_flag=flag,
            )
            assert result.skip_count >= 1
        finally:
            _cleanup_pc(src_dir, dst_dir)
            for f in device.list_files(PHONE_TEST_DIR) or []:
                device.delete(f)


# ---------------------------------------------------------------------------
# Phone→PC 集成测试
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_DEVICE, reason="需要真实 ADB 设备")
class TestPhoneToPcIntegration:
    """Phone→PC 全链路：copy → re-scan 0 diff → delete → re-scan 0 diff。"""

    def test_full_lifecycle_copy_re_scan_delete(self, device):
        """Phone→PC：手机端文件 → 同步到 PC → 再比对 0 差异 → 删除 → 0 差异。"""
        src_dir, dst_dir = _setup_pc_dirs()
        try:
            # 创建单个文件以避免嵌套子目录 phone_src 路径问题
            subprocess.run(
                ["adb", "shell", "echo", "-n", "phone-data",
                 ">", f"{PHONE_TEST_DIR}p.flac"],
                capture_output=True,
            )

            # ── 2. Phone→PC sync ──
            src_files, _ = scan(
                PHONE_TEST_DIR, DEFAULT_AUDIO_EXTENSIONS,
                device=device, cancel_flag=None,
            )
            dest_files_before, _ = scan(
                dst_dir, DEFAULT_AUDIO_EXTENSIONS,
                device=None, cancel_flag=None,
            )
            diffs = compare(src_files, dest_files_before)
            assert len(diffs) == 1
            assert diffs[0].operation == "copy"

            result = execute(
                diffs, PHONE_TEST_DIR, dst_dir,
                source_device=device,
            )
            assert result.success_count == 1, f"Failures: {result.failures}"
            assert result.failure_count == 0

            # ── 3. 再比对 → 0 差异 ──
            src_files2, _ = scan(
                PHONE_TEST_DIR, DEFAULT_AUDIO_EXTENSIONS,
                device=device, cancel_flag=None,
            )
            dest_files2, _ = scan(
                dst_dir, DEFAULT_AUDIO_EXTENSIONS,
                device=None, cancel_flag=None,
            )
            diffs2 = compare(src_files2, dest_files2)
            assert len(diffs2) == 0

            # ── 4. 删除手机端 → PC 端也删除 ──
            for d in diffs:
                phone_path = PHONE_TEST_DIR.rstrip("/") + "/" + d.relative_path
                device.delete(phone_path)

            src_files3, _ = scan(
                PHONE_TEST_DIR, DEFAULT_AUDIO_EXTENSIONS,
                device=device, cancel_flag=None,
            )
            dest_files3, _ = scan(
                dst_dir, DEFAULT_AUDIO_EXTENSIONS,
                device=None, cancel_flag=None,
            )
            diffs3 = compare(src_files3, dest_files3)
            # 删除手机端后，only_in_dest 差异应出现
            assert len(diffs3) >= 1

            result3 = execute(
                diffs3, PHONE_TEST_DIR, dst_dir,
                source_device=device,
            )
            assert result3.success_count == len(diffs3)

            # ── 5. 最终再比对 → 0 差异 ──
            src_files4, _ = scan(
                PHONE_TEST_DIR, DEFAULT_AUDIO_EXTENSIONS,
                device=device, cancel_flag=None,
            )
            dest_files4, _ = scan(
                dst_dir, DEFAULT_AUDIO_EXTENSIONS,
                device=None, cancel_flag=None,
            )
            diffs4 = compare(src_files4, dest_files4)
            assert len(diffs4) == 0

        finally:
            _cleanup_pc(src_dir, dst_dir)
            for f in device.list_files(PHONE_TEST_DIR) or []:
                device.delete(f)
