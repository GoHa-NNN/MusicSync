"""ADB 设备层 — Android Debug Bridge 通信封装。

封装所有 ADB 交互——设备检测、文件枚举、属性获取、传输操作。
为上层模块提供统一的 ``Device`` 抽象，支持依赖注入便于测试。

关键特性:
    - **二进制安全读取**: 使用 ``adb exec-out`` 绕过 PTY，避免 ``\\n`` → ``\\r\\n``
      文本转换污染数据（MusicSync v1 Bug #1 修复）
    - **字节精确定位**: ``dd iflag=skip_bytes,count_bytes`` 确保尾部定位精度
    - **依赖注入**: 构造函数接受 ``adb_path``，测试时可注入 mock

ADB 远程路径使用 ``//sdcard/`` 前缀（双斜杠），避免 Windows 路径解析问题。

Usage::

    from adb_device_kit import Device

    device = Device("adb")              # 使用系统 PATH 中的 adb
    device = Device("path/to/adb.exe")  # 指定 adb 路径

    if device.detect():
        files = device.list_files("//sdcard/Music/")
        info = device.stat(files[0])
        print(f"大小: {info['size']}, 修改时间: {info['modified']}")
"""

import subprocess
import os
from typing import Optional

from .cancel_flag import CancelFlag


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# ADB 命令超时（秒）
CMD_TIMEOUT_SHORT = 15      # devices, stat, rm
CMD_TIMEOUT_LIST = 60       # find 枚举
CMD_TIMEOUT_TRANSFER = 300  # push/pull 传输

# 快速哈希：前 64KB + 后 64KB
QUICK_HASH_CHUNK = 64 * 1024  # 65536 字节


# ---------------------------------------------------------------------------
# 内部辅助：子进程执行
# ---------------------------------------------------------------------------

def _run(adb_path: str, args: list[str], timeout: int = CMD_TIMEOUT_SHORT) -> subprocess.CompletedProcess:
    """执行 ADB 子进程命令（文本输出），统一错误处理。

    Args:
        adb_path: adb 可执行文件路径
        args: ADB 命令参数列表，如 ``["devices", "-l"]``
        timeout: 超时秒数

    Returns:
        ``CompletedProcess`` 对象，调用方取 ``.stdout`` / ``.returncode``

    Raises:
        subprocess.TimeoutExpired: 命令超时
        FileNotFoundError: adb.exe 不存在
    """
    cmd = [adb_path] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="surrogateescape",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _run_bytes(adb_path: str, args: list[str], timeout: int = CMD_TIMEOUT_SHORT) -> bytes:
    """执行 ADB 子进程命令（二进制输出），用于读取文件内容片段。

    Args:
        adb_path: adb 可执行文件路径
        args: ADB 命令参数列表
        timeout: 超时秒数

    Returns:
        命令的 stdout 原始字节；命令失败返回空 ``b""``
    """
    cmd = [adb_path] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode != 0:
        return b""
    return result.stdout


# ---------------------------------------------------------------------------
# Device 类
# ---------------------------------------------------------------------------

class DeviceError(Exception):
    """ADB 设备层错误。

    当 ADB 操作遇到预期外的状态时抛出。
    """

    pass


class Device:
    """封装所有 ADB 操作。

    提供设备检测、文件枚举、属性获取、文件传输、删除、空间查询等功能。
    所有与手机的方法都接受可选的 ``cancel_flag`` 参数用于安全取消长时操作。

    用法::

        device = Device("adb")             # 使用系统 PATH 中的 adb
        device = Device("path/to/adb.exe") # 指定 adb 路径

        if device.detect():
            device_id = device.get_device_info().get("device_id")
            print(f"已连接: {device_id}")

            files = device.list_files("//sdcard/Music/")
            for f in files:
                info = device.stat(f)
                print(f"  {f}: {info['size']} bytes")

            device.push("C:/local/song.flac", "//sdcard/Music/song.flac")

    测试时可通过 mock ``subprocess.run`` 替代真实 ADB 调用::

        import subprocess
        original = subprocess.run
        def fake_run(cmd, **kw):
            # 返回模拟数据
            ...
        subprocess.run = fake_run
        device = Device("fake_adb")
        # 执行测试...
        subprocess.run = original
    """

    def __init__(self, adb_path: str = "adb"):
        """初始化 Device 实例。

        Args:
            adb_path: adb 可执行文件路径。默认为 ``"adb"``（从系统 PATH 查找）。
                      可传入完整路径如 ``"C:/tools/adb.exe"``。
        """
        self.adb_path = adb_path

    # ------------------------------------------------------------------
    # 设备检测
    # ------------------------------------------------------------------

    def detect(self) -> bool:
        """检测是否有已授权的 Android 设备。

        解析 ``adb devices -l`` 输出，检查是否存在状态为 ``device`` 的设备。

        Returns:
            ``True`` 如果至少有一台设备在线且已授权

        用法::

            device = Device()
            if device.detect():
                print("设备已连接")
            else:
                print("未检测到设备——请连接 Android 手机并开启 USB 调试")
        """
        try:
            result = _run(self.adb_path, ["devices", "-l"], timeout=CMD_TIMEOUT_SHORT)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        if result.returncode != 0:
            return False

        for line in result.stdout.strip().split("\n"):
            # 跳过 header: "List of devices attached"
            if line.startswith("List of devices") or not line.strip():
                continue
            if "\tdevice" in line or " device" in line:
                return True
        return False

    def get_device_info(self) -> dict[str, str]:
        """获取已连接设备的信息。

        Returns:
            dict 包含 ``device_id``、``model``、``product`` 等字段；无设备时返回空 dict

        用法::

            info = device.get_device_info()
            # {'device_id': 'f50f82b8', 'model': '23013RK75C', 'product': 'mondrian', ...}
        """
        try:
            result = _run(self.adb_path, ["devices", "-l"], timeout=CMD_TIMEOUT_SHORT)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return {}

        if result.returncode != 0:
            return {}

        for line in result.stdout.strip().split("\n"):
            if line.startswith("List of devices") or not line.strip():
                continue
            # 格式：f50f82b8  device product:mondrian model:23013RK75C device:mondrian ...
            parts = line.strip().split()
            if len(parts) >= 2 and "device" in parts[1]:
                info = {"device_id": parts[0]}
                for part in parts[2:]:
                    if ":" in part:
                        key, val = part.split(":", 1)
                        info[key] = val
                return info
        return {}

    # ------------------------------------------------------------------
    # 文件枚举
    # ------------------------------------------------------------------

    def list_files(self, directory: str, cancel_flag: Optional[CancelFlag] = None) -> list[str]:
        """枚举目录下所有文件的完整 ADB 路径。

        使用 ``adb shell find <dir> -type f`` 命令，返回排序后的完整路径列表。

        Args:
            directory: ADB 远程目录路径，如 ``"//sdcard/Music/"``
            cancel_flag: 可选的取消标志，已设置时立即返回空列表

        Returns:
            文件完整路径列表（按字母序）；目录不存在或空目录返回空列表
            （过滤掉 ``.thumbnails`` 等隐藏文件，但保留所有扩展名的文件——由调用方负责过滤）

        Raises:
            FileNotFoundError: adb 不可用
            subprocess.TimeoutExpired: 命令超时（60 秒）

        用法::

            files = device.list_files("//sdcard/Music/")
            print(f"找到 {len(files)} 个文件")
            for f in files[:5]:
                print(f"  {f}")
        """
        if cancel_flag and cancel_flag.is_set():
            return []

        safe_dir = self._safe_path(directory)
        try:
            result = _run(
                self.adb_path,
                ["shell", f"find {safe_dir} -type f 2>/dev/null"],
                timeout=CMD_TIMEOUT_LIST,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        if result.returncode != 0 and result.returncode != 1:
            # returncode 1 = find 无错误但没找到文件（目录可能为空）
            return []

        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        return sorted(lines)

    # ------------------------------------------------------------------
    # 文件属性
    # ------------------------------------------------------------------

    def stat(self, file_path: str) -> Optional[dict]:
        """获取手机端文件的属性。

        通过 ``adb shell stat -c '%s|%Y'`` 获取文件大小和 Unix 时间戳，
        并将时间戳转换为 ISO 8601 格式。

        Args:
            file_path: ADB 文件路径，如 ``"//sdcard/Music/song.flac"``

        Returns:
            - 成功: ``{"size": int, "modified": str}``，其中 modified 为 ISO 8601 格式
            - 文件不存在: ``None``

        用法::

            info = device.stat("//sdcard/Music/song.flac")
            if info:
                print(f"大小: {info['size']} bytes")
                print(f"修改时间: {info['modified']}")
        """
        safe_path = self._safe_path(file_path)
        # stat -c: %s=字节大小, %Y=Unix时间戳（秒）
        try:
            result = _run(
                self.adb_path,
                ["shell", f"stat -c '%s|%Y' {safe_path} 2>/dev/null"],
                timeout=CMD_TIMEOUT_SHORT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        output = result.stdout.strip()
        if not output:
            return None

        parts = output.split("|")
        if len(parts) != 2:
            return None

        try:
            size = int(parts[0])
            mtime_unix = int(parts[1])
        except (ValueError, IndexError):
            return None

        from datetime import datetime, timezone

        mtime_iso = datetime.fromtimestamp(mtime_unix, tz=timezone.utc).isoformat()
        return {"size": size, "modified": mtime_iso}

    # ------------------------------------------------------------------
    # 文件内容片段读取（快速哈希用）
    # ------------------------------------------------------------------

    def read_head_tail(
        self, file_path: str, chunk_size: int = QUICK_HASH_CHUNK, cancel_flag: Optional[CancelFlag] = None
    ) -> tuple[bytes, bytes]:
        """读取手机端文件的头部和尾部字节（二进制安全）。

        **关键技术细节**: 使用 ``adb exec-out`` 而非 ``adb shell``。
        ``exec-out`` 绕过 PTY 伪终端，避免 PTY 的 ``\\n`` → ``\\r\\n`` 文本转换污染二进制数据。
        使用 ``dd iflag=count_bytes,skip_bytes`` 确保以**字节**（而非块）为单位精确读取。

        MusicSync v1 Bug #1 修复: 旧代码使用 ``adb shell`` + ``dd bs=N skip=N count=1``
        块模式，导致两个问题：
        1. PTY 污染 — 二进制数据被破坏
        2. 块级截断 — ``(file_size - chunk_size) // chunk_size`` 整数除法导致尾部偏移

        Args:
            file_path: ADB 文件路径
            chunk_size: 读取块大小（默认 65536 = 64KB）。文件小于此值时头部包含全部内容、尾部为空
            cancel_flag: 可选的取消标志

        Returns:
            ``(head_bytes, tail_bytes)`` — 各自最多 chunk_size 字节。
            文件不存在或读取出错时返回对应位置的空 bytes。

        用法::

            head, tail = device.read_head_tail("//sdcard/Music/song.flac")
            # head: 文件前 64KB（二进制字节）
            # tail: 文件后 64KB（二进制字节）
            # 可用于计算快速哈希: SHA-256(head + tail + file_size)
        """
        if cancel_flag and cancel_flag.is_set():
            return (b"", b"")

        safe_path = self._safe_path(file_path)
        head = b""
        tail = b""

        # 使用 exec-out 而非 shell：exec-out 绕过 PTY 伪终端
        # iflag=count_bytes 确保以字节而非块为单位精确读取

        # 读取文件头部
        try:
            head = _run_bytes(
                self.adb_path,
                ["exec-out", f"dd if={safe_path} iflag=count_bytes count={chunk_size} status=none"],
                timeout=CMD_TIMEOUT_SHORT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        if cancel_flag and cancel_flag.is_set():
            return (head, b"")

        # 读取文件尾部：iflag=skip_bytes,count_bytes 以字节精度跳过
        info = self.stat(file_path)
        if info is None:
            return (head, b"")

        file_size = info["size"]
        if file_size <= chunk_size:
            # 文件小于 chunk_size，头部已包含全部内容，尾部为空
            return (head, b"")

        skip_bytes = file_size - chunk_size
        try:
            tail = _run_bytes(
                self.adb_path,
                ["exec-out", f"dd if={safe_path} iflag=skip_bytes,count_bytes skip={skip_bytes} count={chunk_size} status=none"],
                timeout=CMD_TIMEOUT_SHORT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return (head, tail)

    # ------------------------------------------------------------------
    # 文件传输
    # ------------------------------------------------------------------

    def push(self, local_path: str, remote_path: str, cancel_flag: Optional[CancelFlag] = None) -> bool:
        """将本地文件推送到手机。

        Args:
            local_path: PC 端文件绝对路径，如 ``"C:/Music/song.flac"``
            remote_path: 手机端目标路径，如 ``"//sdcard/Music/song.flac"``
            cancel_flag: 可选的取消标志

        Returns:
            ``True`` 成功，``False`` 失败（超时 / 设备断开 / 空间不足等）

        用法::

            ok = device.push("C:/Music/song.flac", "//sdcard/Music/song.flac")
            if not ok:
                print("推送失败")
        """
        if cancel_flag and cancel_flag.is_set():
            return False

        # push/pull 不需要 shell 引号包裹——直接传 ADB 路径
        if not remote_path.startswith("//"):
            remote_path = "//" + remote_path.lstrip("/")

        try:
            result = _run(
                self.adb_path,
                ["push", local_path, remote_path],
                timeout=CMD_TIMEOUT_TRANSFER,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        # adb push 成功时信息输出到 stderr（非 stdout）
        return result.returncode == 0 and "error" not in result.stderr.lower()

    def pull(self, remote_path: str, local_path: str, cancel_flag: Optional[CancelFlag] = None) -> bool:
        """从手机拉取文件到本地。

        Args:
            remote_path: 手机端文件路径，如 ``"//sdcard/Music/song.flac"``
            local_path: PC 端目标路径，如 ``"C:/backup/song.flac"``
            cancel_flag: 可选的取消标志

        Returns:
            ``True`` 成功，``False`` 失败

        用法::

            ok = device.pull("//sdcard/Music/song.flac", "C:/backup/song.flac")
            if ok:
                print("拉取成功")
        """
        if cancel_flag and cancel_flag.is_set():
            return False

        if not remote_path.startswith("//"):
            remote_path = "//" + remote_path.lstrip("/")

        try:
            result = _run(
                self.adb_path,
                ["pull", remote_path, local_path],
                timeout=CMD_TIMEOUT_TRANSFER,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        return result.returncode == 0 and "error" not in result.stderr.lower()

    # ------------------------------------------------------------------
    # 文件删除
    # ------------------------------------------------------------------

    def delete(self, remote_path: str, cancel_flag: Optional[CancelFlag] = None) -> bool:
        """删除手机端文件。

        执行 ``rm -f`` 后调用 ``stat`` 验证文件确实不存在。

        Args:
            remote_path: 要删除的手机端文件路径
            cancel_flag: 可选的取消标志

        Returns:
            ``True`` 删除成功（stat 验证文件不存在），``False`` 失败

        用法::

            if device.delete("//sdcard/Music/old_song.flac"):
                print("已删除")
        """
        if cancel_flag and cancel_flag.is_set():
            return False

        safe_path = self._safe_path(remote_path)
        try:
            result = _run(
                self.adb_path,
                ["shell", f"rm -f {safe_path}"],
                timeout=CMD_TIMEOUT_SHORT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

        # 验证文件已删除
        if result.returncode == 0:
            info = self.stat(remote_path)
            return info is None  # stat 返回 None 表示文件确实不存在
        return False

    # ------------------------------------------------------------------
    # 空间检查
    # ------------------------------------------------------------------

    def get_free_space(self, directory: str = "//sdcard/") -> Optional[int]:
        """获取手机端剩余空间。

        通过 ``adb shell df -k`` 解析 Available 列。

        Args:
            directory: 要查询的目录（默认 ``"//sdcard/"``）

        Returns:
            剩余空间字节数；获取失败返回 ``None``

        用法::

            free = device.get_free_space()
            if free:
                gb = free / (1024 ** 3)
                print(f"剩余空间: {gb:.1f} GB")
        """
        safe_dir = self._safe_path(directory)
        try:
            result = _run(
                self.adb_path,
                ["shell", f"df -k {safe_dir} 2>/dev/null"],
                timeout=CMD_TIMEOUT_SHORT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        output = result.stdout.strip()
        if not output:
            return None

        # df -k 输出格式：
        # Filesystem     1K-blocks    Used Available Use% Mounted on
        # /dev/fuse      234463212 162029388  72302752  70% /storage/emulated
        lines = output.split("\n")
        if len(lines) < 2:
            return None

        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    avail_kb = int(parts[3])
                    return avail_kb * 1024  # KB → 字节
                except (ValueError, IndexError):
                    continue
        return None

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_path(path: str) -> str:
        """将路径转为 ADB shell 安全引用格式。

        使用单引号包裹防止 shell 特殊字符（空格、``$``、``(`` 等）被解析，
        路径内部单引号被转义。

        Args:
            path: 原始路径，如 ``"/sdcard/Music/My Songs/"``

        Returns:
            shell 安全引用字符串，如 ``"'//sdcard/Music/My Songs/'"``
        """
        # 处理路径内单引号：' → '\''
        escaped = path.replace("'", "'\\''")
        # 确保 double-slash 前缀
        if not escaped.startswith("//"):
            escaped = "//" + escaped.lstrip("/")
        return f"'{escaped}'"
