"""test_sync_engine_scan.py — scan() PC 本地扫描集成测试（用 tmp_path）。"""

import os
import pytest
from musicsync.core.sync_engine import scan


# ---------------------------------------------------------------------------
# 基本扫描
# ---------------------------------------------------------------------------

class TestScanBasic:
    def test_empty_directory(self, tmp_path):
        """空目录返回空列表。"""
        files, skipped = scan(str(tmp_path), extensions=["flac", "mp3"])
        assert files == []

    def test_audio_files_only(self, tmp_path):
        """扫描应返回白名单内的音频文件。"""
        os.makedirs(tmp_path / "sub")
        (tmp_path / "song.flac").write_bytes(b"a" * 100)
        (tmp_path / "sub" / "track.mp3").write_bytes(b"b" * 200)

        files, skipped = scan(str(tmp_path), extensions=["flac", "mp3"])
        assert len(files) == 2
        relative_paths = {f.relative_path for f in files}
        assert "song.flac" in relative_paths
        assert "sub/track.mp3" in relative_paths

    def test_non_audio_filtered(self, tmp_path):
        """非白名单文件被跳过。"""
        (tmp_path / "song.flac").write_bytes(b"a")
        (tmp_path / "cover.jpg").write_bytes(b"b")
        (tmp_path / "playlist.m3u").write_bytes(b"c")

        files, skipped = scan(str(tmp_path), extensions=["flac"])
        assert len(files) == 1
        assert files[0].relative_path == "song.flac"

    def test_skipped_info_collected(self, tmp_path):
        """scan() 应收集 SkippedInfo 统计。"""
        (tmp_path / "song.flac").write_bytes(b"a")
        (tmp_path / "cover.jpg").write_bytes(b"b")
        (tmp_path / "note.txt").write_bytes(b"c")

        files, skipped = scan(str(tmp_path), extensions=["flac"])
        assert skipped.total == 2  # jpg + txt


# ---------------------------------------------------------------------------
# 相对路径 — 根路径前缀剥离
# ---------------------------------------------------------------------------

class TestRelativePath:
    def test_prefix_stripped(self, tmp_path):
        """relative_path 不包含根路径前缀。"""
        os.makedirs(tmp_path / "deep" / "nested")
        (tmp_path / "deep" / "nested" / "song.flac").write_bytes(b"x")

        files, skipped = scan(str(tmp_path), extensions=["flac"])
        assert len(files) == 1
        assert files[0].relative_path == "deep/nested/song.flac"

    def test_path_separator_normalized(self, tmp_path):
        """Windows 反斜杠被规范化为正斜杠。"""
        os.makedirs(tmp_path / "a" / "b")
        (tmp_path / "a" / "b" / "song.flac").write_bytes(b"x")

        files, skipped = scan(str(tmp_path), extensions=["flac"])
        assert "\\" not in files[0].relative_path
        assert files[0].relative_path == "a/b/song.flac"


# ---------------------------------------------------------------------------
# FileInfo 字段
# ---------------------------------------------------------------------------

class TestFileInfoFields:
    def test_size_populated(self, tmp_path):
        """FileInfo.size 应为实际字节数。"""
        (tmp_path / "song.flac").write_bytes(b"x" * 1234)

        files, skipped = scan(str(tmp_path), extensions=["flac"])
        assert len(files) == 1
        assert files[0].size == 1234

    def test_modified_populated(self, tmp_path):
        """FileInfo.modified 应为 ISO 8601 格式字符串。"""
        (tmp_path / "song.flac").write_bytes(b"x")

        files, skipped = scan(str(tmp_path), extensions=["flac"])
        assert files[0].modified is not None
        assert "T" in files[0].modified  # ISO 8601

    def test_full_path_populated(self, tmp_path):
        """FileInfo.path 应为完整文件路径。"""
        (tmp_path / "song.flac").write_bytes(b"x")

        files, skipped = scan(str(tmp_path), extensions=["flac"])
        assert os.path.isabs(files[0].path)
        assert files[0].path.endswith("song.flac")


# ---------------------------------------------------------------------------
# .musicignore
# ---------------------------------------------------------------------------

class TestMusicignore:
    def test_ignore_glob(self, tmp_path):
        """.musicignore 的 glob 规则正确排除文件。"""
        (tmp_path / "song.flac").write_bytes(b"a")
        (tmp_path / "cover.jpg").write_bytes(b"b")

        files, skipped = scan(
            str(tmp_path),
            extensions=["flac", "jpg"],
            musicignore_rules=["*.jpg"],
        )
        assert len(files) == 1
        assert files[0].relative_path == "song.flac"

    def test_ignore_directory(self, tmp_path):
        """.musicignore 的目录规则正确排除。"""
        os.makedirs(tmp_path / "temp" / "stuff")
        (tmp_path / "song.flac").write_bytes(b"a")
        (tmp_path / "temp" / "stuff" / "inside.flac").write_bytes(b"b")

        files, skipped = scan(
            str(tmp_path),
            extensions=["flac"],
            musicignore_rules=["temp/"],
        )
        relative_paths = {f.relative_path for f in files}
        assert "song.flac" in relative_paths
        assert "temp/stuff/inside.flac" not in relative_paths

    def test_no_musicignore(self, tmp_path):
        """无 .musicignore 时不报错，正常返回。"""
        (tmp_path / "song.flac").write_bytes(b"a")

        files, skipped = scan(str(tmp_path), extensions=["flac"])
        assert len(files) == 1


# ---------------------------------------------------------------------------
# CancelFlag
# ---------------------------------------------------------------------------

class TestScanCancel:
    def test_cancel_returns_empty(self, tmp_path):
        """cancel_flag 已设置时立即返回空列表。"""
        from musicsync.adb_device_kit.cancel_flag import CancelFlag

        (tmp_path / "song.flac").write_bytes(b"a")
        flag = CancelFlag()
        flag.cancel()

        files, skipped = scan(str(tmp_path), extensions=["flac"], cancel_flag=flag)
        assert files == []


# ---------------------------------------------------------------------------
# 多种扩展名
# ---------------------------------------------------------------------------

class TestMultipleExtensions:
    def test_case_insensitive(self, tmp_path):
        """扩展名大小写无关。"""
        (tmp_path / "song.FLAC").write_bytes(b"a")
        (tmp_path / "track.MP3").write_bytes(b"b")

        files, skipped = scan(str(tmp_path), extensions=["flac", "mp3"])
        assert len(files) == 2
