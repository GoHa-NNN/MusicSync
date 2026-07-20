"""test_device.py — Device ADB 设备层单元测试 + 真实设备集成测试。

覆盖:
    - 设备检测成功/失败/未授权/离线/adb 不存在
    - find 输出解析（正常/空目录/超时）
    - stat 输出解析（正常/不存在/格式错误）
    - push/pull 模拟（成功/失败/超时）
    - 删除逻辑（rm + stat 验证）
    - 空间检查（正常/失败）
    - 真实设备集成测试（需要 ADB 授权设备连接）
"""

import unittest
import subprocess

from musicsync.adb_device_kit.device import Device


# ---------------------------------------------------------------------------
# 模拟 subprocess.run 的 fixture
# ---------------------------------------------------------------------------

class FakeCompletedProcess:
    """模拟 subprocess.CompletedProcess。"""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


# ---------------------------------------------------------------------------
# 单元测试：设备检测
# ---------------------------------------------------------------------------

class TestDeviceDetect(unittest.TestCase):
    """测试设备检测逻辑（mock subprocess）。"""

    def test_detect_success(self):
        """一台设备在线时应返回 True。"""
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout="List of devices attached\nf50f82b8\tdevice\n",
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            self.assertTrue(device.detect())
        finally:
            subprocess.run = original_run

    def test_detect_no_device(self):
        """没有设备时应返回 False。"""
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout="List of devices attached\n",
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            self.assertFalse(device.detect())
        finally:
            subprocess.run = original_run

    def test_detect_unauthorized(self):
        """未授权设备不应被检测为在线。"""
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout="List of devices attached\nf50f82b8\tunauthorized\n",
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            self.assertFalse(device.detect())
        finally:
            subprocess.run = original_run

    def test_detect_offline(self):
        """离线设备不应被检测为在线。"""
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout="List of devices attached\nf50f82b8\toffline\n",
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            self.assertFalse(device.detect())
        finally:
            subprocess.run = original_run

    def test_detect_adb_not_found(self):
        """adb.exe 不存在时返回 False。"""
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            raise FileNotFoundError()

        subprocess.run = fake_run
        try:
            self.assertFalse(device.detect())
        finally:
            subprocess.run = original_run

    def test_get_device_info(self):
        """正确解析设备信息。"""
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout="List of devices attached\nf50f82b8\tdevice product:mondrian model:23013RK75C device:mondrian\n",
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            info = device.get_device_info()
            self.assertEqual(info["device_id"], "f50f82b8")
            self.assertEqual(info["product"], "mondrian")
            self.assertEqual(info["model"], "23013RK75C")
        finally:
            subprocess.run = original_run


# ---------------------------------------------------------------------------
# 单元测试：文件枚举
# ---------------------------------------------------------------------------

class TestDeviceListFiles(unittest.TestCase):
    """测试文件枚举逻辑（mock subprocess）。"""

    def test_list_files_normal(self):
        """正常枚举应返回排序后的路径列表。"""
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout="//sdcard/Music/a.flac\n//sdcard/Music/z.mp3\n//sdcard/Music/sub/b.flac\n",
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            files = device.list_files("//sdcard/Music/")
            self.assertEqual(len(files), 3)
            self.assertEqual(files[0], "//sdcard/Music/a.flac")
            self.assertEqual(files[-1], "//sdcard/Music/z.mp3")
        finally:
            subprocess.run = original_run

    def test_list_files_empty_dir(self):
        """空目录返回空列表。"""
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(stdout="", returncode=0)

        subprocess.run = fake_run
        try:
            files = device.list_files("//sdcard/Music/")
            self.assertEqual(len(files), 0)
        finally:
            subprocess.run = original_run

    def test_list_files_timeout(self):
        """超时应返回空列表。"""
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 30)

        subprocess.run = fake_run
        try:
            files = device.list_files("//sdcard/Music/")
            self.assertEqual(len(files), 0)
        finally:
            subprocess.run = original_run


# ---------------------------------------------------------------------------
# 单元测试：stat
# ---------------------------------------------------------------------------

class TestDeviceStat(unittest.TestCase):
    """测试 stat 解析逻辑。"""

    def test_stat_normal(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout="26580279|1774850631",
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            info = device.stat("//sdcard/Music/song.flac")
            self.assertIsNotNone(info)
            self.assertEqual(info["size"], 26580279)
            self.assertIsNotNone(info["modified"])
            self.assertIn("T", info["modified"])  # ISO 8601 包含 T 分隔符
        finally:
            subprocess.run = original_run

    def test_stat_file_not_found(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(stdout="", returncode=1)

        subprocess.run = fake_run
        try:
            info = device.stat("//sdcard/Music/nonexistent.flac")
            self.assertIsNone(info)
        finally:
            subprocess.run = original_run

    def test_stat_malformed_output(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(stdout="garbage", returncode=0)

        subprocess.run = fake_run
        try:
            info = device.stat("//sdcard/Music/garbage.flac")
            self.assertIsNone(info)
        finally:
            subprocess.run = original_run


# ---------------------------------------------------------------------------
# 单元测试：传输
# ---------------------------------------------------------------------------

class TestDeviceTransfer(unittest.TestCase):
    """测试 push/pull 逻辑。"""

    def test_push_success(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout="",
                stderr="test.txt: 1 file pushed. 0 skipped.",
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            self.assertTrue(device.push("C:\\test.txt", "//sdcard/test.txt"))
        finally:
            subprocess.run = original_run

    def test_push_failure(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(stdout="", stderr="error: device not found", returncode=1)

        subprocess.run = fake_run
        try:
            self.assertFalse(device.push("C:\\test.txt", "//sdcard/test.txt"))
        finally:
            subprocess.run = original_run

    def test_pull_success(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout="",
                stderr="//sdcard/test.txt: 1 file pulled.",
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            self.assertTrue(device.pull("//sdcard/test.txt", "C:\\dest.txt"))
        finally:
            subprocess.run = original_run

    def test_push_timeout(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 30)

        subprocess.run = fake_run
        try:
            self.assertFalse(device.push("C:\\test.txt", "//sdcard/test.txt"))
        finally:
            subprocess.run = original_run


# ---------------------------------------------------------------------------
# 单元测试：删除
# ---------------------------------------------------------------------------

class TestDeviceDelete(unittest.TestCase):
    """测试删除逻辑。"""

    def test_delete_success(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # rm 命令成功
                return FakeCompletedProcess(stdout="", returncode=0)
            else:
                # stat 验证：文件已删除
                return FakeCompletedProcess(stdout="", returncode=1)

        subprocess.run = fake_run
        try:
            self.assertTrue(device.delete("//sdcard/test.txt"))
        finally:
            subprocess.run = original_run


# ---------------------------------------------------------------------------
# 单元测试：空间
# ---------------------------------------------------------------------------

class TestDeviceFreeSpace(unittest.TestCase):
    """测试空间检查逻辑。"""

    def test_free_space_normal(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(
                stdout=(
                    "Filesystem     1K-blocks      Used Available Use% Mounted on\n"
                    "/dev/fuse      234463212 162028880  72303260  70% /storage/emulated"
                ),
                returncode=0,
            )

        subprocess.run = fake_run
        try:
            free = device.get_free_space()
            self.assertIsNotNone(free)
            self.assertEqual(free, 72303260 * 1024)
        finally:
            subprocess.run = original_run

    def test_free_space_failure(self):
        device = Device("fake_adb")
        original_run = subprocess.run

        def fake_run(cmd, **kwargs):
            return FakeCompletedProcess(stdout="", returncode=1)

        subprocess.run = fake_run
        try:
            free = device.get_free_space()
            self.assertIsNone(free)
        finally:
            subprocess.run = original_run


# ---------------------------------------------------------------------------
# 集成测试（需要真实 ADB 设备）
# ---------------------------------------------------------------------------

class TestDeviceIntegration(unittest.TestCase):
    """真实设备集成测试——需要 ADB 授权设备连接。

    跳过条件：无设备连接时测试通过（标记为跳过）。
    """

    def setUp(self):
        self.device = Device("adb")

    def test_detect_real(self):
        """真实设备检测。"""
        detected = self.device.detect()
        if detected:
            self.assertTrue(detected)
        else:
            self.skipTest("没有连接的 ADB 设备")

    def test_list_files_real(self):
        """真实设备文件枚举。"""
        if not self.device.detect():
            self.skipTest("没有连接的 ADB 设备")
        files = self.device.list_files("//sdcard/Music/")
        self.assertGreater(len(files), 0)
        for f in files[:5]:
            self.assertTrue(f.startswith("//sdcard/"))

    def test_stat_real(self):
        """真实设备 stat。"""
        if not self.device.detect():
            self.skipTest("没有连接的 ADB 设备")
        files = self.device.list_files("//sdcard/Music/")
        if not files:
            self.skipTest("手机 Music 目录为空")
        info = self.device.stat(files[0])
        self.assertIsNotNone(info)
        self.assertIn("size", info)
        self.assertIn("modified", info)

    def test_read_head_tail_real(self):
        """真实设备读取文件片段（二进制安全 exec-out 模式）。"""
        if not self.device.detect():
            self.skipTest("没有连接的 ADB 设备")
        files = self.device.list_files("//sdcard/Music/")
        for f in files:
            info = self.device.stat(f)
            if info and info["size"] > 0:
                head, tail = self.device.read_head_tail(f)
                self.assertGreater(len(head), 0)
                break
        else:
            self.skipTest("没有非空文件可测试")

    def test_free_space_real(self):
        """真实设备空间查询。"""
        if not self.device.detect():
            self.skipTest("没有连接的 ADB 设备")
        free = self.device.get_free_space()
        self.assertIsNotNone(free)
        self.assertGreater(free, 0)

    def test_push_pull_delete_real(self):
        """真实设备传输全流程（push → stat → pull → 内容校验 → delete → stat 验证）。"""
        if not self.device.detect():
            self.skipTest("没有连接的 ADB 设备")

        import tempfile
        import os

        tmpdir = tempfile.mkdtemp()
        test_file = os.path.join(tmpdir, "test.txt")
        test_data = b"MusicSync_Integration_Test_" + b"X" * 512

        try:
            with open(test_file, "wb") as f:
                f.write(test_data)

            # push
            self.assertTrue(
                self.device.push(test_file, "//sdcard/MusicSync_itest.txt"),
                "push 失败",
            )

            # stat 验证
            info = self.device.stat("//sdcard/MusicSync_itest.txt")
            self.assertIsNotNone(info)
            self.assertEqual(info["size"], len(test_data))

            # pull 验证
            pull_file = os.path.join(tmpdir, "back.txt")
            self.assertTrue(
                self.device.pull("//sdcard/MusicSync_itest.txt", pull_file),
                "pull 失败",
            )
            with open(pull_file, "rb") as f:
                self.assertEqual(f.read(), test_data, "pull 内容不匹配")

            # delete
            self.assertTrue(
                self.device.delete("//sdcard/MusicSync_itest.txt"),
                "delete 失败",
            )
            self.assertIsNone(
                self.device.stat("//sdcard/MusicSync_itest.txt"),
                "文件应该已被删除",
            )
        finally:
            for f in [test_file, os.path.join(tmpdir, "back.txt")]:
                if os.path.exists(f):
                    os.unlink(f)
            os.rmdir(tmpdir)
            self.device.delete("//sdcard/MusicSync_itest.txt")


if __name__ == "__main__":
    unittest.main()
