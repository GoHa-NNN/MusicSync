"""test_pipe_deadlock.py — 验证 _run Popen 路径管道缓冲区死锁 Bug。

当 cancel_flag 非 None 时，_run 使用 Popen + poll 循环，但不从
stdout/stderr 管道读取数据。子进程输出超过管道缓冲区（Windows ~64KB）
时，子进程阻塞在 write()，父进程阻塞在 poll()，形成死锁。

此 Bug 导致 Phone 扫描大目录（>~500 个文件路径）时必然超时 60 秒，
然后静默返回空列表，最终比对结果显示 0 差异。
"""

import subprocess
import time
import pytest

from musicsync.adb_device_kit.cancel_flag import CancelFlag
from musicsync.adb_device_kit.device import _run


# ---------------------------------------------------------------------------
# 死锁复现
# ---------------------------------------------------------------------------

def test_run_with_cancel_flag_does_not_deadlock_on_large_output():
    """cancel_flag 非 None 时应正确读取子进程全部 stdout 而不死锁。"""
    # 生成 ~128KB 的 Python 代码，超过 Windows 管道缓冲区
    script = (
        "import sys; "
        "sys.stdout.write('x' * 131072); "  # 128KB
        "sys.stdout.flush()"
    )

    flag = CancelFlag()

    t0 = time.monotonic()
    result = _run(
        "python", ["-c", script],
        timeout=5,
        cancel_flag=flag,
    )
    elapsed = time.monotonic() - t0

    assert elapsed < 4.0, (
        f"死锁或超时：耗时 {elapsed:.1f}s（预期 <4s）。"
        f"\n子进程输出 128KB 超过管道缓冲区，若不在 poll 时同步读取 stdout "
        f"则子进程永远阻塞在 write()。"
    )
    assert result.returncode == 0
    assert len(result.stdout) >= 131072, (
        f"stdout 不完整：{len(result.stdout)} bytes（预期 >=131072）。"
        f"管道数据可能被截断或丢失。"
    )


def test_run_without_cancel_flag_still_works():
    """cancel_flag=None 时 subprocess.run 路径仍然正常（回归测试）。"""
    script = "import sys; sys.stdout.write('hello'); sys.stdout.flush()"

    result = _run("python", ["-c", script], timeout=5, cancel_flag=None)
    assert result.returncode == 0
    assert result.stdout == "hello"


def test_run_small_output_with_cancel_flag():
    """小输出（<管道缓冲区）时 Popen 路径应正常工作。"""
    # 这个测试验证为什么小目录扫描能成功——
    # 327 首歌的路径约 14KB 输出，未超过 64KB 管道缓冲区
    lines = [f"//sdcard/Music/track_{i:04d}.flac" for i in range(300)]
    script = (
        "import sys; "
        f"sys.stdout.write({repr(chr(10).join(lines))}); "
        "sys.stdout.flush()"
    )

    flag = CancelFlag()

    result = _run("python", ["-c", script], timeout=3, cancel_flag=flag)
    assert result.returncode == 0
    assert len(result.stdout.split("\n")) == 300


def test_cancel_flag_interrupts_long_running_command():
    """cancel_flag 设置后应在 0.5s 内中断子进程。"""
    flag = CancelFlag()

    # 启动一个长时间运行的命令
    import threading
    def cancel_after_delay():
        import time as _time
        _time.sleep(0.2)
        flag.cancel()

    t = threading.Thread(target=cancel_after_delay)
    t.start()

    t0 = time.monotonic()
    # python 休眠 10 秒 — 应被 cancel 中断
    from musicsync.adb_device_kit.cancel_flag import CancelledError
    with pytest.raises(CancelledError):
        _run("python", ["-c", "import time; time.sleep(10)"],
             timeout=10, cancel_flag=flag)

    elapsed = time.monotonic() - t0
    assert elapsed < 0.8, (
        f"取消不应等待子进程完成：耗时 {elapsed:.1f}s"
    )
    t.join()


def test_timeout_on_silent_process():
    """即使无输出，超时也应生效。"""
    flag = CancelFlag()
    t0 = time.monotonic()

    with pytest.raises(subprocess.TimeoutExpired):
        _run("python", ["-c", "import time; time.sleep(10)"],
             timeout=0.5, cancel_flag=flag)

    elapsed = time.monotonic() - t0
    assert elapsed < 1.5, f"超时应快速生效：{elapsed:.1f}s"
