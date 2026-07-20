"""文件过滤器 — 音频扩展名白名单 + .musicignore 规则。

纯函数设计，无 I/O 依赖。``.musicignore`` 内容由调用方传入字符串，
解析失败时静默回退，不影响主流程。

核心组件:
    - ``parse_musicignore()`` — 解析 .musicignore 文件内容为规则列表
    - ``matches_any_rule()`` — 检查相对路径是否匹配任意规则
    - ``AudioFilter`` — 音频文件过滤器（白名单 + 可选忽略规则）

Usage::

    from adb_device_kit import AudioFilter, parse_musicignore

    # 从文件加载 .musicignore
    with open("Music/.musicignore", "r") as f:
        rules_content = f.read()

    f = AudioFilter(musicignore_content=rules_content)
    if f.should_include("VOCALOID/song.flac"):
        print("包含此文件")
    else:
        print("跳过此文件")

    # 查看跳过统计
    summary = f.get_skipped_summary()
    print(f"跳过 {summary.total} 个文件")
"""

import os
import fnmatch
from typing import Optional

from .models import SkippedInfo


# ---------------------------------------------------------------------------
# 内置默认白名单
# ---------------------------------------------------------------------------

DEFAULT_AUDIO_EXTENSIONS = ["flac", "mp3", "wav", "aac", "ogg", "m4a", "wma"]


# ---------------------------------------------------------------------------
# .musicignore 解析
# ---------------------------------------------------------------------------

def parse_musicignore(content: str) -> list[str]:
    """解析 ``.musicignore`` 文件内容为规则列表。

    规则语法同 ``.gitignore``（子集）:
        - ``#`` 开头的行为注释
        - 空行忽略
        - 其他行视为 glob 模式（如 ``*.jpg``、``临时/``）

    Args:
        content: ``.musicignore`` 文件的完整文本内容

    Returns:
        非注释、非空行的规则列表

    用法::

        rules = parse_musicignore("# 图片\\n*.jpg\\n*.png\\n临时/\\n")
        # ['*.jpg', '*.png', '临时/']
    """
    rules: list[str] = []
    for line in content.split("\n"):
        stripped = line.rstrip("\r").strip()
        if not stripped or stripped.startswith("#"):
            continue
        rules.append(stripped)
    return rules


def matches_any_rule(relative_path: str, rules: list[str]) -> bool:
    """检查相对路径是否匹配任意一条 ``.musicignore`` 规则。

    匹配逻辑:
        - 规则以 ``/`` 结尾 → 目录规则，检查路径中是否包含该目录名
        - 其他规则 → 使用 ``fnmatch`` 做 glob 匹配（对文件名和完整路径均检查）
        - 同时检查 Unix 风格 (``/``) 和 Windows 风格 (``\\``) 路径

    Args:
        relative_path: 文件的相对路径，如 ``"VOCALOID/cover.jpg"``
        rules: ``parse_musicignore()`` 返回的规则列表

    Returns:
        ``True`` 如果文件应被排除

    用法::

        rules = ["*.jpg", "临时/"]
        matches_any_rule("VOCALOID/cover.jpg", rules)   # True (glob 匹配)
        matches_any_rule("临时/song.flac", rules)         # True (目录规则)
        matches_any_rule("VOCALOID/song.flac", rules)     # False
    """
    if not rules:
        return False

    basename = os.path.basename(relative_path)
    for rule in rules:
        # 目录规则（以 / 结尾）
        if rule.endswith("/"):
            dir_pattern = rule.rstrip("/")
            # 检查路径中是否包含该目录
            parts = relative_path.replace("\\", "/").split("/")
            if dir_pattern in parts:
                return True
            continue

        # glob 匹配：先对文件名匹配，再对完整路径匹配
        if fnmatch.fnmatch(basename, rule):
            return True
        if fnmatch.fnmatch(relative_path, rule):
            return True
        # 也试 Windows 风格路径
        if fnmatch.fnmatch(relative_path.replace("/", "\\"), rule):
            return True

    return False


# ---------------------------------------------------------------------------
# AudioFilter 类
# ---------------------------------------------------------------------------

class AudioFilter:
    """音频文件过滤器。

    组合**扩展名白名单**和可选的 **.musicignore 规则**进行过滤。

    属性:
        extensions (list[str]): 当前生效的音频扩展名列表（小写，不含点）
        musicignore_rules (list[str]): 当前生效的 .musicignore 规则列表

    用法::

        # 默认白名单（7 种格式）
        f = AudioFilter()

        # 自定义白名单
        f = AudioFilter(["flac", "mp3"])

        # 带 .musicignore 排除规则
        f = AudioFilter(musicignore_content="*.jpg\\n临时/\\n")

        # 判断单个文件
        if f.should_include("path/to/song.flac"):
            print("包含")

        # 批量过滤
        kept, skipped = f.filter(file_list, side="source")

        # 查看统计
        summary = f.get_skipped_summary()
        print(f"跳过 {summary.total} 个: {summary.by_extension}")
    """

    def __init__(
        self,
        extensions: Optional[list[str]] = None,
        musicignore_content: Optional[str] = None,
    ):
        """初始化过滤器。

        Args:
            extensions: 自定义音频扩展名列表（如 ``["flac", "mp3"]``）。
                        默认使用 ``DEFAULT_AUDIO_EXTENSIONS``（7 种格式）。
                        大小写无关，前导 ``.`` 会被自动去除。
            musicignore_content: ``.musicignore`` 文件的文本内容。
                                 ``None`` 或空字符串表示不启用忽略规则。
        """
        self.extensions = [e.lower().lstrip(".") for e in (extensions or DEFAULT_AUDIO_EXTENSIONS)]
        self.musicignore_rules: list[str] = []
        if musicignore_content:
            try:
                self.musicignore_rules = parse_musicignore(musicignore_content)
            except Exception:
                # 解析失败静默回退
                self.musicignore_rules = []

        # 跳过的文件记录
        self._skipped: list[str] = []
        self._skipped_by_side: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 核心过滤
    # ------------------------------------------------------------------

    def should_include(self, file_path: str) -> bool:
        """检查单个文件是否应被包含。

        两阶段检查:
            1. 扩展名必须在白名单中
            2. 路径不能匹配任何 .musicignore 规则

        Args:
            file_path: 文件路径（绝对或相对均可）

        Returns:
            ``True`` 应包含，``False`` 应跳过

        用法::

            f = AudioFilter()
            f.should_include("music/song.flac")   # True
            f.should_include("music/cover.jpg")    # False (非音频扩展名)
        """
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        if ext not in self.extensions:
            return False

        if self.musicignore_rules:
            if matches_any_rule(file_path, self.musicignore_rules):
                return False

        return True

    def filter(self, file_list: list[str], side: str = "source") -> tuple[list[str], list[str]]:
        """批量过滤文件列表，同时记录跳过统计。

        Args:
            file_list: 文件路径列表
            side: 设备端标识（如 ``"source"`` / ``"dest"``），用于分组统计

        Returns:
            ``(kept, skipped)`` — 保留的和跳过的文件列表

        用法::

            f = AudioFilter()
            kept, skipped = f.filter(files, side="source")
            print(f"保留 {len(kept)} 个，跳过 {len(skipped)} 个")
        """
        kept: list[str] = []
        skipped: list[str] = []

        for f in file_list:
            if self.should_include(f):
                kept.append(f)
            else:
                skipped.append(f)

        self._skipped.extend(skipped)
        self._skipped_by_side[side] = self._skipped_by_side.get(side, 0) + len(skipped)

        return kept, skipped

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_skipped_summary(self) -> SkippedInfo:
        """返回跳过文件统计。

        Returns:
            ``SkippedInfo`` 对象，包含:
                - ``total``: 跳过文件总数
                - ``by_extension``: 按扩展名分组的计数
                - ``by_side``: 按设备端分组的计数
                - ``file_list``: 被跳过的文件完整路径列表

        用法::

            summary = f.get_skipped_summary()
            print(f"跳过了 {summary.total} 个文件")
            for ext, count in summary.by_extension.items():
                print(f"  {ext}: {count}")
        """
        by_ext: dict[str, int] = {}
        for f in self._skipped:
            ext = os.path.splitext(f)[1].lower()
            if ext:
                by_ext[ext] = by_ext.get(ext, 0) + 1
            else:
                by_ext["(无扩展名)"] = by_ext.get("(无扩展名)", 0) + 1

        return SkippedInfo(
            total=len(self._skipped),
            by_extension=by_ext,
            by_side=self._skipped_by_side,
            file_list=self._skipped.copy(),
        )

    def reset_skipped(self) -> None:
        """重置跳过统计计数器。

        在开始新的扫描前调用，防止统计数据跨扫描累积。

        用法::

            f = AudioFilter()
            # 第一次扫描
            f.filter(files_source, side="source")
            # ... 使用统计 ...
            f.reset_skipped()
            # 第二次扫描（全新统计）
            f.filter(files_dest, side="dest")
        """
        self._skipped.clear()
        self._skipped_by_side.clear()
