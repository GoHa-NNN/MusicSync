"""cli.py — MusicSync 命令行入口。

用法::

    python -m musicsync.cli <源目录> <目的目录>

PC→PC 单向镜像同步全链路：扫描 → 比对 → 展示差异 → 确认 → 执行 → 记录历史。
"""

import os
import sys
import sqlite3

from musicsync.adb_device_kit.cancel_flag import CancelFlag
from musicsync.adb_device_kit.filter_utils import (
    parse_musicignore,
    DEFAULT_AUDIO_EXTENSIONS,
)
from musicsync.adb_device_kit.executor_helpers import format_size
from musicsync.core.sync_engine import scan, compare
from musicsync.core.executor import execute
from musicsync.store.database import init_db, record_operation, get_setting


def main() -> None:
    if len(sys.argv) != 3:
        print("用法: python -m musicsync.cli <源目录> <目的目录>")
        sys.exit(1)

    source_root = sys.argv[1]
    dest_root = sys.argv[2]

    if not os.path.isdir(source_root):
        print(f"错误: 源目录不存在 — {source_root}")
        sys.exit(1)
    if not os.path.isdir(dest_root):
        print(f"错误: 目的目录不存在 — {dest_root}")
        sys.exit(1)

    # ── 加载设置 ──────────────────────────────────────────
    conn = sqlite3.connect("musicsync.db")
    init_db(conn)

    extensions_str = get_setting(conn, "audio_extensions")
    extensions = _parse_extensions(extensions_str)

    # ── 加载 .musicignore ─────────────────────────────────
    musicignore_rules = _load_musicignore(source_root)

    # ── 扫描 ─────────────────────────────────────────────
    cancel_flag = CancelFlag()
    print(f"\nMusicSync — PC→PC 单向镜像同步")
    print(f"源:   {source_root}")
    print(f"目的: {dest_root}\n")

    print("[扫描源端...]", end=" ")
    source_files, src_skipped = scan(
        source_root, extensions, musicignore_rules, cancel_flag=cancel_flag,
    )
    print(f"找到 {len(source_files)} 个文件", end="")
    if src_skipped.total:
        print(f"（跳过 {src_skipped.total} 个非音频）", end="")
    print()

    print("[扫描目的端...]", end=" ")
    dest_files, dst_skipped = scan(
        dest_root, extensions, musicignore_rules, cancel_flag=cancel_flag,
    )
    print(f"找到 {len(dest_files)} 个文件", end="")
    if dst_skipped.total:
        print(f"（跳过 {dst_skipped.total} 个非音频）", end="")
    print()

    # ── 比对 ─────────────────────────────────────────────
    print("[比对...]", end=" ")
    diffs = compare(source_files, dest_files, cancel_flag=cancel_flag)
    print(f"发现 {len(diffs)} 项差异\n")

    if not diffs:
        print("两端一致——无需同步。")
        conn.close()
        return

    # ── 展示差异 ─────────────────────────────────────────
    _print_diffs(diffs)

    # ── 确认 ─────────────────────────────────────────────
    total_bytes = sum(d.source_size or 0 for d in diffs if d.operation != "delete")
    print(f"\n共 {len(diffs)} 项差异 | 预估传输量 {format_size(total_bytes)}")
    ans = input("\n确认执行？(y/n): ").strip().lower()
    if ans != "y":
        print("已取消。")
        conn.close()
        return

    # ── 执行 ─────────────────────────────────────────────
    print()
    result = execute(diffs, source_root, dest_root, cancel_flag=cancel_flag)

    # 仅成功的操作写入历史
    succeeded_paths = {f[0] for f in result.failures}
    for d in diffs:
        if d.selected and d.relative_path not in succeeded_paths:
            record_operation(
                conn,
                action_type=d.operation,
                direction=d.direction,
                relative_path=d.relative_path,
                file_size=d.source_size or d.dest_size or 0,
            )

    # ── 摘要 ─────────────────────────────────────────────
    print(f"\n完成！成功 {result.success_count}，失败 {result.failure_count}", end="")
    if result.total_bytes_transferred:
        print(f"，传输 {format_size(result.total_bytes_transferred)}", end="")
    if result.skip_count:
        print(f"，跳过 {result.skip_count}", end="")
    print()

    if result.failures:
        print("\n失败详情:")
        for path, err in result.failures:
            print(f"  ✗ {path}: {err}")

    conn.close()


# ---------------------------------------------------------------------------
# 输出辅助
# ---------------------------------------------------------------------------

def _print_diffs(diffs: list[object]) -> None:
    """按操作类型分组展示差异列表。"""
    groups = {"copy": [], "overwrite": [], "delete": []}
    for d in diffs:
        groups[d.operation].append(d)

    labels = {
        "copy": "复制到目的",
        "overwrite": "覆盖目的",
        "delete": "从目的删除",
    }

    for op in ("copy", "overwrite", "delete"):
        items = groups[op]
        if not items:
            continue
        print(f"  {labels[op]} ({len(items)}):")
        for d in items:
            size_str = format_size(d.source_size or d.dest_size or 0)
            if op == "copy":
                print(f"    NEW  {d.relative_path}  {size_str}")
            elif op == "overwrite":
                old = format_size(d.dest_size or 0)
                new = format_size(d.source_size or 0)
                print(f"    UPD  {d.relative_path}  {old} → {new}")
            else:
                print(f"    DEL  {d.relative_path}  {size_str}")


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _parse_extensions(raw: str | None) -> list[str]:
    """从 JSON 数组字符串解析扩展名列表。"""
    if not raw:
        return list(DEFAULT_AUDIO_EXTENSIONS)
    try:
        import json
        exts = json.loads(raw)
        return [e.lower().lstrip(".") for e in exts]
    except (json.JSONDecodeError, TypeError):
        return list(DEFAULT_AUDIO_EXTENSIONS)


def _load_musicignore(root: str) -> list[str] | None:
    """加载 <root>/.musicignore 文件内容并解析为规则列表。"""
    path = os.path.join(root, ".musicignore")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        rules = parse_musicignore(content)
        return rules if rules else None
    except OSError:
        return None


if __name__ == "__main__":
    main()
