"""test_hash.py — quick_hash + compute_local_hash 测试。

覆盖:
    - 确定性（相同输入 → 相同输出）
    - 区分性（不同头/尾/大小 → 不同哈希）
    - SHA-256 格式验证
    - 小文件 / 大文件 / 不存在文件
    - 已知向量验证
"""

import unittest
import os
import hashlib
import tempfile
import shutil

from adb_device_kit.hash_utils import quick_hash, compute_local_hash, QUICK_HASH_CHUNK


# ============================================================================
# quick_hash 纯函数测试
# ============================================================================

class TestQuickHash(unittest.TestCase):
    """测试快速哈希纯函数。"""

    def test_deterministic(self):
        """相同输入应产生相同输出。"""
        h1 = quick_hash(b"head", b"tail", 100)
        h2 = quick_hash(b"head", b"tail", 100)
        self.assertEqual(h1, h2)

    def test_different_head_different_hash(self):
        """不同头部 → 不同哈希。"""
        h1 = quick_hash(b"aaa", b"tail", 100)
        h2 = quick_hash(b"bbb", b"tail", 100)
        self.assertNotEqual(h1, h2)

    def test_different_tail_different_hash(self):
        """不同尾部 → 不同哈希。"""
        h1 = quick_hash(b"head", b"aaa", 100)
        h2 = quick_hash(b"head", b"bbb", 100)
        self.assertNotEqual(h1, h2)

    def test_different_size_different_hash(self):
        """不同文件大小 → 不同哈希。"""
        h1 = quick_hash(b"head", b"tail", 100)
        h2 = quick_hash(b"head", b"tail", 200)
        self.assertNotEqual(h1, h2)

    def test_sha256_format(self):
        """输出应为 64 字符十六进制字符串。"""
        h = quick_hash(b"data", b"more", 42)
        self.assertEqual(len(h), 64)
        # 应为纯十六进制
        int(h, 16)

    def test_empty_head_tail(self):
        """空头部和尾部的边界情况。"""
        h = quick_hash(b"", b"", 0)
        self.assertEqual(len(h), 64)

    def test_known_vector(self):
        """用 Python hashlib 独立计算验证。"""
        head = b"A" * 65536   # 64KB
        tail = b"B" * 65536
        size = 200000
        expected_input = head + tail + b"200000"
        expected = hashlib.sha256(expected_input).hexdigest()
        self.assertEqual(quick_hash(head, tail, size), expected)


# ============================================================================
# compute_local_hash 测试
# ============================================================================

class TestComputeLocalHash(unittest.TestCase):
    """测试本地文件快速哈希计算。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_small_file(self):
        """小于 64KB 的文件：头部包含全部内容，尾部为空。"""
        path = os.path.join(self.tmpdir, "small.bin")
        data = b"X" * 1000
        with open(path, "wb") as f:
            f.write(data)

        h = compute_local_hash(path, len(data))
        expected = quick_hash(data, b"", len(data))
        self.assertEqual(h, expected)

    def test_large_file(self):
        """大于 128KB 的文件：取前 64KB + 后 64KB。"""
        path = os.path.join(self.tmpdir, "large.bin")
        data = b"A" * 65536 + b"MIDDLE" + b"B" * 65536
        with open(path, "wb") as f:
            f.write(data)

        h = compute_local_hash(path, len(data))
        expected_head = data[:65536]
        expected_tail = data[-65536:]
        expected = quick_hash(expected_head, expected_tail, len(data))
        self.assertEqual(h, expected)

    def test_nonexistent_file(self):
        """不存在的文件返回 None。"""
        h = compute_local_hash(
            os.path.join(self.tmpdir, "nonexistent.bin"), 100
        )
        self.assertIsNone(h)

    def test_exactly_chunk_size(self):
        """恰好 64KB 的文件：头部 = 全部内容，尾部 = 空。"""
        path = os.path.join(self.tmpdir, "exact.bin")
        data = b"C" * QUICK_HASH_CHUNK
        with open(path, "wb") as f:
            f.write(data)

        h = compute_local_hash(path, len(data))
        expected = quick_hash(data, b"", len(data))
        self.assertEqual(h, expected)


if __name__ == "__main__":
    unittest.main()
