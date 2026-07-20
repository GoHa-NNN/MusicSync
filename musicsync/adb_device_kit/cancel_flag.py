"""线程安全取消标志。

用于在多线程操作（如 ADB 传输、文件扫描）中安全地传递取消信号。
基于 threading.Event，可在任意线程中设置和检查。

Usage::

    from adb_device_kit import CancelFlag, CancelledError

    flag = CancelFlag()

    # 在 worker 线程中周期性检查:
    def do_work(flag):
        for item in items:
            if flag.is_set():
                return  # 收到取消信号，安全退出
            process(item)

    # 在 UI 线程中取消:
    flag.cancel()
"""

import threading


class CancelledError(Exception):
    """操作被 CancelFlag 取消时抛出。

    在 subprocess.Popen 轮询循环中检测到 cancel_flag.is_set() 后抛出，
    由调用方（如 Device 方法）捕获并转换为对应的返回值（False / [] / b""）。
    """

    pass


class CancelFlag:
    """线程安全取消标志。

    封装 ``threading.Event``，提供简洁的 ``cancel()`` / ``is_set()`` / ``reset()`` 接口。

    典型用法::

        flag = CancelFlag()

        # 启动 worker 线程
        import threading
        t = threading.Thread(target=worker, args=(flag,))
        t.start()

        # 用户点击取消
        flag.cancel()
        t.join()
    """

    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        """设置取消标志。

        调用后所有 ``is_set()`` 检查将返回 ``True``。
        幂等操作——重复调用无副作用。
        """
        self._event.set()

    def is_set(self) -> bool:
        """检查是否已取消。

        Returns:
            ``True`` 如果已调用 ``cancel()``
        """
        return self._event.is_set()

    def reset(self) -> None:
        """重置取消标志（用于启动新的操作）。

        调用后 ``is_set()`` 恢复返回 ``False``。
        """
        self._event.clear()
