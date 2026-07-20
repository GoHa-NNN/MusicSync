"""快速文件哈希 — 高性能文件内容指纹。

基于 SHA-256 的快速文件哈希算法，仅读取文件的前 64KB 和后 64KB
（而非整个文件），适用于数 GB 的大文件快速比对。

算法: ``SHA-256(前64KB + 后64KB + 文件大小)``

这是纯逻辑模块，不依赖任何外部库或本包其他模块。

Usage::

    from adb_device_kit import quick_hash, compute_local_hash

    # 方式 1: 纯函数（已有字节数据时）
    h = quick_hash(head_bytes, tail_bytes, file_size)

    # 方式 2: 直接从本地文件计算
    h = compute_local_hash("C:/Music/song.flac", os.path.getsize("C:/Music/song.flac"))
"""

import os
import hashlib
from typing import Optional


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

QUICK_HASH_CHUNK = 64 * 1024  # 64KB


# ---------------------------------------------------------------------------
# 纯函数：快速哈希计算
# ---------------------------------------------------------------------------

def quick_hash(head: bytes, tail: bytes, file_size: int) -> str:
    """计算快速哈希值：SHA-256(前64KB + 后64KB + 文件大小)。

    纯函数，无 I/O 依赖。给定文件头尾字节和大小，返回确定性哈希值。

    Args:
        head: 文件头部字节（通常为前 64KB，小文件时为全部内容）
        tail: 文件尾部字节（通常为后 64KB，小文件时为空）
        file_size: 文件总大小（字节），作为哈希输入的一部分确保不同大小文件产生不同哈希

    Returns:
        64 字符十六进制 SHA-256 哈希字符串

    用法::

        h = quick_hash(b"head_bytes...", b"tail_bytes...", 1234567)
        print(h)  # "a1b2c3d4e5f6..."

    算法保证:
        - 确定性: 相同输入永远产生相同输出
        - 区分性: 不同 head/tail/size 产生不同输出（SHA-256 抗碰撞性）
        - 格式: 始终为 64 字符小写十六进制
    """
    data = head + tail + str(file_size).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# 本地文件哈希
# ---------------------------------------------------------------------------

def compute_local_hash(file_path: str, file_size: int) -> Optional[str]:
    """计算本地文件的快速哈希值。

    读取文件的头部和尾部片段，调用 ``quick_hash()`` 计算最终哈希。
    对于小于 QUICK_HASH_CHUNK (64KB) 的文件，读取**整个文件**作为头部，尾部为空。

    Args:
        file_path: 本地文件绝对路径（PC 端）
        file_size: 文件大小（字节），可通过 ``os.path.getsize(path)`` 获取

    Returns:
        - 成功: 64 字符十六进制哈希字符串
        - 文件不存在或读取失败: ``None``

    用法::

        import os
        path = "C:/Music/song.flac"
        size = os.path.getsize(path)
        h = compute_local_hash(path, size)
        if h:
            print(f"哈希: {h}")

    示例——验证两个文件是否相同::

        h1 = compute_local_hash("file1.flac", os.path.getsize("file1.flac"))
        h2 = compute_local_hash("file2.flac", os.path.getsize("file2.flac"))
        if h1 and h2 and h1 == h2:
            print("两个文件内容相同")
    """
    try:
        if file_size <= QUICK_HASH_CHUNK:
            with open(file_path, "rb") as f:
                head = f.read()
            return quick_hash(head, b"", file_size)

        with open(file_path, "rb") as f:
            head = f.read(QUICK_HASH_CHUNK)
            f.seek(-QUICK_HASH_CHUNK, os.SEEK_END)
            tail = f.read(QUICK_HASH_CHUNK)
        return quick_hash(head, tail, file_size)
    except (OSError, IOError):
        return None
