"""test_filter.py — parse_musicignore / matches_any_rule / AudioFilter 测试。

覆盖:
    - .musicignore 解析：空内容、注释、规则、尾部空格、CRLF
    - glob 匹配：basename、完整路径、目录规则、通配符、大小写
    - AudioFilter 白名单：默认/自定义扩展名、包含/排除
    - AudioFilter + .musicignore 混合过滤
    - 批量过滤与统计
    - reset_skipped 功能
"""

import unittest

from musicsync.adb_device_kit.filter_utils import (
    AudioFilter,
    parse_musicignore,
    matches_any_rule,
    DEFAULT_AUDIO_EXTENSIONS,
)


# ---------------------------------------------------------------------------
# parse_musicignore
# ---------------------------------------------------------------------------

class TestParseMusicignore(unittest.TestCase):
    """测试 .musicignore 解析。"""

    def test_empty_content(self):
        self.assertEqual(parse_musicignore(""), [])

    def test_only_comments_and_blanks(self):
        content = """
        # this is a comment
        # another comment

        """
        self.assertEqual(parse_musicignore(content), [])

    def test_simple_rules(self):
        content = """
        # images
        *.jpg
        *.png
        # temp folders
        临时/
        """
        rules = parse_musicignore(content)
        self.assertEqual(rules, ["*.jpg", "*.png", "临时/"])

    def test_trailing_whitespace(self):
        content = "*.jpg   \n  *.tmp  \n"
        rules = parse_musicignore(content)
        self.assertEqual(rules, ["*.jpg", "*.tmp"])

    def test_mixed_crlf(self):
        content = "# header\r\n*.jpg\r\n*.png"
        rules = parse_musicignore(content)
        self.assertEqual(rules, ["*.jpg", "*.png"])


# ---------------------------------------------------------------------------
# matches_any_rule
# ---------------------------------------------------------------------------

class TestMatchesAnyRule(unittest.TestCase):
    """测试 .musicignore 规则匹配。"""

    def test_empty_rules(self):
        self.assertFalse(matches_any_rule("image.jpg", []))

    def test_glob_match_basename(self):
        rules = ["*.jpg", "*.tmp"]
        self.assertTrue(matches_any_rule("VOCALOID/cover.jpg", rules))
        self.assertTrue(matches_any_rule("C:\\Music\\temp.tmp", rules))
        self.assertFalse(matches_any_rule("song.flac", rules))

    def test_glob_match_full_path(self):
        rules = ["VOCALOID/*"]
        self.assertTrue(matches_any_rule("VOCALOID/test.flac", rules))

    def test_directory_rule(self):
        rules = ["临时/", "temp/"]
        self.assertTrue(matches_any_rule("临时/song.flac", rules))
        self.assertTrue(matches_any_rule("music/temp/file.mp3", rules))
        self.assertFalse(matches_any_rule("VOCALOID/song.flac", rules))

    def test_wildcard_glob(self):
        rules = ["*.nomedia"]
        self.assertTrue(matches_any_rule(".thumbnails/.nomedia", rules))

    def test_case_sensitivity(self):
        """.musicignore glob 大小写不敏感？fnmatch 在 Windows 上默认不敏感。"""
        rules = ["*.JPG"]
        self.assertTrue(matches_any_rule("photo.jpg", rules))


# ---------------------------------------------------------------------------
# AudioFilter 白名单
# ---------------------------------------------------------------------------

class TestAudioFilterWhitelist(unittest.TestCase):
    """测试白名单过滤。"""

    def test_default_extensions(self):
        f = AudioFilter()
        self.assertIn("flac", f.extensions)
        self.assertIn("mp3", f.extensions)
        self.assertIn("wav", f.extensions)

    def test_custom_extensions(self):
        f = AudioFilter(["FLAC", "MP3"])
        self.assertEqual(f.extensions, ["flac", "mp3"])

    def test_include_audio(self):
        f = AudioFilter()
        self.assertTrue(f.should_include("E:\\Music\\song.flac"))
        self.assertTrue(f.should_include("E:\\Music\\song.MP3"))
        self.assertTrue(f.should_include("//sdcard/Music/song.wav"))

    def test_exclude_non_audio(self):
        f = AudioFilter()
        self.assertFalse(f.should_include("E:\\Music\\cover.jpg"))
        self.assertFalse(f.should_include("E:\\Music\\.nomedia"))
        self.assertFalse(f.should_include("E:\\Music\\.database_uuid"))
        self.assertFalse(f.should_include("E:\\Music\\notes.txt"))

    def test_no_extension(self):
        f = AudioFilter()
        self.assertFalse(f.should_include("E:\\Music\\Makefile"))
        self.assertFalse(f.should_include("README"))

    def test_dotfile_with_audio_ext(self):
        """以 . 开头的隐藏文件即使扩展名匹配也要考虑——当前逻辑只看扩展名。"""
        f = AudioFilter()
        self.assertTrue(f.should_include(".hidden.flac"))


# ---------------------------------------------------------------------------
# AudioFilter + .musicignore
# ---------------------------------------------------------------------------

class TestAudioFilterWithIgnore(unittest.TestCase):
    """测试白名单 + .musicignore 混合过滤。"""

    def setUp(self):
        self.musicignore = """
        *.jpg
        *.tmp
        临时/
        """
        self.f = AudioFilter(musicignore_content=self.musicignore)

    def test_include_audio_not_ignored(self):
        self.assertTrue(self.f.should_include("VOCALOID/song.flac"))

    def test_exclude_ignored_audio_file(self):
        # .tmp 被 .musicignore glob 排除
        self.assertFalse(self.f.should_include("song.tmp"))

    def test_exclude_ignored_directory(self):
        """被忽略目录下的音频文件也应排除。"""
        self.assertFalse(self.f.should_include("临时/song.flac"))

    def test_ignore_parsing_failure(self):
        """解析失败时静默回退。"""
        f = AudioFilter(musicignore_content=None)  # None → rules=[]
        self.assertTrue(f.should_include("song.flac"))


# ---------------------------------------------------------------------------
# filter() 批量过滤 + 统计
# ---------------------------------------------------------------------------

class TestAudioFilterBatch(unittest.TestCase):
    """测试批量过滤和统计。"""

    def test_filter_returns_two_lists(self):
        f = AudioFilter()
        files = ["E:\\Music\\a.flac", "E:\\Music\\b.jpg", "E:\\Music\\c.mp3", "E:\\Music\\d.tmp"]
        kept, skipped = f.filter(files)
        self.assertEqual(kept, ["E:\\Music\\a.flac", "E:\\Music\\c.mp3"])
        self.assertEqual(skipped, ["E:\\Music\\b.jpg", "E:\\Music\\d.tmp"])

    def test_filter_with_ignore_rules(self):
        f = AudioFilter(musicignore_content="*.tmp\n")
        files = ["a.flac", "b.tmp", "c.mp3"]
        kept, skipped = f.filter(files)
        self.assertEqual(kept, ["a.flac", "c.mp3"])
        self.assertEqual(skipped, ["b.tmp"])

    def test_side_tracking(self):
        f = AudioFilter()
        f.filter(["a.flac", "b.jpg"], side="source")
        f.filter(["c.flac", "d.tmp", "e.jpg"], side="dest")

        summary = f.get_skipped_summary()
        self.assertEqual(summary.total, 3)
        self.assertEqual(summary.by_side["source"], 1)
        self.assertEqual(summary.by_side["dest"], 2)

    def test_summary_by_extension(self):
        f = AudioFilter()
        f.filter(["a.flac", "b.jpg", "c.jpg", "d.tmp", "e.png"])

        summary = f.get_skipped_summary()
        self.assertEqual(summary.total, 4)
        self.assertIn(".jpg", summary.by_extension)
        self.assertEqual(summary.by_extension[".jpg"], 2)
        self.assertIn(".tmp", summary.by_extension)
        self.assertIn(".png", summary.by_extension)

    def test_summary_no_extension(self):
        f = AudioFilter()
        f.filter(["a.flac", "Makefile", "README"])

        summary = f.get_skipped_summary()
        self.assertIn("(无扩展名)", summary.by_extension)
        self.assertEqual(summary.by_extension["(无扩展名)"], 2)

    def test_file_list_in_summary(self):
        f = AudioFilter()
        f.filter(["a.flac", "b.jpg", "c.jpg"])
        summary = f.get_skipped_summary()
        self.assertIn("b.jpg", summary.file_list)
        self.assertIn("c.jpg", summary.file_list)

    def test_empty_filter(self):
        f = AudioFilter()
        kept, skipped = f.filter([])
        self.assertEqual(kept, [])
        self.assertEqual(skipped, [])
        self.assertEqual(f.get_skipped_summary().total, 0)


# ---------------------------------------------------------------------------
# reset_skipped 测试（v2 新增功能）
# ---------------------------------------------------------------------------

class TestResetSkipped(unittest.TestCase):
    """测试 reset_skipped() 功能。"""

    def test_reset_clears_all_counters(self):
        f = AudioFilter()
        f.filter(["a.flac", "b.jpg", "c.jpg"], side="source")

        # 重置前有数据
        summary = f.get_skipped_summary()
        self.assertGreater(summary.total, 0)

        # 重置
        f.reset_skipped()

        # 重置后所有统计清零
        summary = f.get_skipped_summary()
        self.assertEqual(summary.total, 0)
        self.assertEqual(summary.by_extension, {})
        self.assertEqual(summary.by_side, {})
        self.assertEqual(summary.file_list, [])

    def test_reset_then_new_filter(self):
        """重置后再过滤，统计应仅包含新数据。"""
        f = AudioFilter()
        f.filter(["a.flac", "b.jpg"], side="source")
        f.reset_skipped()
        f.filter(["c.flac", "d.jpg"], side="dest")

        summary = f.get_skipped_summary()
        self.assertEqual(summary.total, 1)  # 仅 d.jpg
        self.assertEqual(summary.by_side.get("source", 0), 0)
        self.assertEqual(summary.by_side.get("dest", 0), 1)


# ---------------------------------------------------------------------------
# 真实场景测试
# ---------------------------------------------------------------------------

class TestRealWorldScenarios(unittest.TestCase):
    """模拟真实场景。"""

    def test_phone_music_dir(self):
        """模拟手机 Music 目录：含 .thumbnails/、ringtone/、杂文件。"""
        f = AudioFilter()
        files = [
            "//sdcard/Music/VOCALOID/song.flac",
            "//sdcard/Music/VOCALOID/cover.jpg",
            "//sdcard/Music/.thumbnails/1000000293.jpg",
            "//sdcard/Music/.thumbnails/.database_uuid",
            "//sdcard/Music/.escheck.tmp",
            "//sdcard/Music/VOCALOID/song2.mp3",
            "//sdcard/Music/ringtone/ringtone.ogg",
            "//sdcard/Music/ringtone/ringtone.wav",
        ]
        kept, skipped = f.filter(files, side="dest")
        self.assertEqual(kept, [
            "//sdcard/Music/VOCALOID/song.flac",
            "//sdcard/Music/VOCALOID/song2.mp3",
            "//sdcard/Music/ringtone/ringtone.ogg",
            "//sdcard/Music/ringtone/ringtone.wav",
        ])
        self.assertEqual(len(skipped), 4)

    def test_default_audio_extensions_list(self):
        """验证默认白名单包含 spec 约定的 7 种格式。"""
        self.assertEqual(DEFAULT_AUDIO_EXTENSIONS, ["flac", "mp3", "wav", "aac", "ogg", "m4a", "wma"])


if __name__ == "__main__":
    unittest.main()
