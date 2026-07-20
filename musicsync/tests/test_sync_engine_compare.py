"""test_sync_engine_compare.py — compare() 纯函数单元测试。

所有比对场景用构造的 FileInfo 列表验证，不走文件系统。
"""

import pytest
from musicsync.adb_device_kit.models import FileInfo
from musicsync.core.sync_engine import compare


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _src(relative_path: str, size: int) -> FileInfo:
    """构造源端 FileInfo，只填比对相关的字段。"""
    return FileInfo(
        path=f"C:/Music/{relative_path}",
        relative_path=relative_path,
        size=size,
    )


def _dst(relative_path: str, size: int) -> FileInfo:
    """构造目的端 FileInfo。"""
    return FileInfo(
        path=f"D:/Backup/{relative_path}",
        relative_path=relative_path,
        size=size,
    )


# ---------------------------------------------------------------------------
# synced — 应被过滤，不在结果中出现
# ---------------------------------------------------------------------------

class TestSynced:
    def test_same_size_excluded(self):
        """相对路径匹配 + 大小相同 → 不在差异列表中。"""
        src = [_src("song.flac", 1000)]
        dst = [_dst("song.flac", 1000)]
        result = compare(src, dst)
        assert len(result) == 0

    def test_multiple_all_synced(self):
        """所有文件都 synced → 空列表。"""
        src = [_src(f"track{i}.flac", i * 100) for i in range(10)]
        dst = [_dst(f"track{i}.flac", i * 100) for i in range(10)]
        result = compare(src, dst)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# new_in_dest — 仅在源端
# ---------------------------------------------------------------------------

class TestNewInDest:
    def test_only_in_source(self):
        """仅在源端 → new_in_dest / copy 操作。"""
        src = [_src("new.flac", 5000)]
        dst = []
        result = compare(src, dst)
        assert len(result) == 1
        d = result[0]
        assert d.relative_path == "new.flac"
        assert d.diff_type == "new_in_dest"
        assert d.operation == "copy"
        assert d.source_size == 5000
        assert d.dest_size is None

    def test_mixed_with_synced(self):
        """部分在两端，部分仅在源端。"""
        src = [_src("old.flac", 100), _src("new.flac", 200)]
        dst = [_dst("old.flac", 100)]
        result = compare(src, dst)
        assert len(result) == 1
        assert result[0].relative_path == "new.flac"


# ---------------------------------------------------------------------------
# only_in_dest — 仅在目的端
# ---------------------------------------------------------------------------

class TestOnlyInDest:
    def test_only_in_dest(self):
        """仅在目的端 → only_in_dest / delete 操作。"""
        src = []
        dst = [_dst("stale.flac", 3000)]
        result = compare(src, dst)
        assert len(result) == 1
        d = result[0]
        assert d.relative_path == "stale.flac"
        assert d.diff_type == "only_in_dest"
        assert d.operation == "delete"
        assert d.source_size is None
        assert d.dest_size == 3000

    def test_mixed(self):
        """源端和目的端各有独占文件。"""
        src = [_src("a.flac", 1)]
        dst = [_dst("b.flac", 2)]
        result = compare(src, dst)
        assert len(result) == 2
        diff_types = {d.diff_type for d in result}
        assert "new_in_dest" in diff_types
        assert "only_in_dest" in diff_types


# ---------------------------------------------------------------------------
# updated_in_dest — 两端都有、大小不同、哈希不同
# ---------------------------------------------------------------------------

class TestUpdatedInDest:
    def test_different_size(self):
        """相对路径匹配 + 大小不同 → updated_in_dest / overwrite 操作。"""
        src = [_src("changed.flac", 9999)]
        dst = [_dst("changed.flac", 8888)]
        result = compare(src, dst)
        assert len(result) == 1
        d = result[0]
        assert d.diff_type == "updated_in_dest"
        assert d.operation == "overwrite"
        assert d.source_size == 9999
        assert d.dest_size == 8888

    def test_different_size_same_hash(self):
        """大小不同但哈希相同 → synced（内容相同，不覆盖）。"""
        # 构造两个大小不同但通过源码分析可知首尾 64KB 相同的文件…
        # 实际上在纯函数层面无法模拟 "大小不同但 content 相同"
        # 的快速哈希碰撞 — 大不同必定导致末尾偏移不同。
        # 我们通过一个参数化验证：如果 hash 字段已预先填充且相同，
        # compare() 应将它们视为 synced。
        src = [FileInfo(
            path="C:/Music/s.flac", relative_path="s.flac",
            size=200000, hash="abc123",
        )]
        dst = [FileInfo(
            path="D:/Backup/s.flac", relative_path="s.flac",
            size=100000, hash="abc123",
        )]
        result = compare(src, dst)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# 路径规范化
# ---------------------------------------------------------------------------

class TestRelativePathMatching:
    def test_unix_vs_windows_paths(self):
        """两端的 relative_path 均为正斜杠，直接字符串比较。"""
        src = [_src("subdir/song.flac", 100)]
        # 目的端相对路径相同（均为正斜杠）
        dst = [FileInfo(
            path="D:\\Backup\\subdir\\song.flac",
            relative_path="subdir/song.flac",
            size=100,
        )]
        result = compare(src, dst)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# CancelFlag 测试
# ---------------------------------------------------------------------------

class TestCancelFlag:
    def test_cancel_returns_empty(self):
        """cancel_flag 已设置时返回空列表。"""
        from musicsync.adb_device_kit.cancel_flag import CancelFlag

        flag = CancelFlag()
        flag.cancel()
        src = [_src("a.flac", 100)]
        dst = []
        result = compare(src, dst, cancel_flag=flag)
        assert result == []


# ---------------------------------------------------------------------------
# 大量文件 + selected 默认值
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_selected_defaults_to_true(self):
        """差异项的 selected 默认为 True。"""
        src = [_src("song.flac", 100)]
        dst = []
        result = compare(src, dst)
        assert result[0].selected is True

    def test_direction_populated(self):
        """direction 字段在比对阶段填充。"""
        src = [_src("song.flac", 100)]
        dst = []
        result = compare(src, dst)
        assert result[0].direction != ""

    def test_large_dataset(self):
        """大量文件的比对正确完成。"""
        src = [_src(f"track{i}.flac", 1000) for i in range(500)]
        dst = [_dst(f"track{i}.flac", 1000) for i in range(0, 500, 2)]
        result = compare(src, dst)
        # 每偶数 0..498 有匹配 → 250 个 synced
        # 每奇数 1..499 仅在源 → 250 个 new_in_dest
        assert len(result) == 250
        assert all(d.diff_type == "new_in_dest" for d in result)
