"""test_cancel_flag.py — CancelFlag 线程安全取消标志测试。"""

import unittest
import threading
import time

from adb_device_kit.cancel_flag import CancelFlag


class TestCancelFlagBasic(unittest.TestCase):
    """基本功能测试。"""

    def test_not_set_initially(self):
        """新建标志不应被设置。"""
        cf = CancelFlag()
        self.assertFalse(cf.is_set())

    def test_cancel_sets_flag(self):
        """cancel() 后 is_set() 应返回 True。"""
        cf = CancelFlag()
        cf.cancel()
        self.assertTrue(cf.is_set())

    def test_reset_clears_flag(self):
        """reset() 后 is_set() 应恢复返回 False。"""
        cf = CancelFlag()
        cf.cancel()
        cf.reset()
        self.assertFalse(cf.is_set())

    def test_cancel_is_idempotent(self):
        """重复 cancel() 无副作用。"""
        cf = CancelFlag()
        cf.cancel()
        cf.cancel()
        self.assertTrue(cf.is_set())

    def test_reset_when_not_set(self):
        """未设置时 reset() 无副作用。"""
        cf = CancelFlag()
        cf.reset()
        self.assertFalse(cf.is_set())


class TestCancelFlagThreading(unittest.TestCase):
    """多线程安全测试。"""

    def test_cancel_from_another_thread(self):
        """从其他线程取消，主线程应能检测到。"""
        cf = CancelFlag()

        def delayed_cancel():
            time.sleep(0.05)
            cf.cancel()

        t = threading.Thread(target=delayed_cancel)
        t.start()
        self.assertFalse(cf.is_set())  # 还没到 0.05s
        t.join()
        self.assertTrue(cf.is_set())  # 已取消

    def test_check_during_loop(self):
        """模拟 worker 线程中的检查模式。"""
        cf = CancelFlag()
        results = []

        def worker():
            for i in range(100):
                if cf.is_set():
                    results.append("cancelled")
                    return
                results.append(i)
                time.sleep(0.001)

        t = threading.Thread(target=worker)
        t.start()
        time.sleep(0.02)
        cf.cancel()
        t.join()
        self.assertIn("cancelled", results)
        # 不应该跑完 100 次
        self.assertLess(len([r for r in results if isinstance(r, int)]), 100)


if __name__ == "__main__":
    unittest.main()
