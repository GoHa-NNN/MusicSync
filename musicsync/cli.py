"""cli.py — MusicSync 命令行入口。

用法::

    python -m musicsync.cli <源目录> <目的目录>
    python -m musicsync.cli --dest-device phone <源目录> <手机路径>
    python -m musicsync.cli --source-device phone <手机路径> <目的目录>

单向镜像同步全链路：扫描 → 比对 → 展示差异 → 确认 → 执行 → 记录历史。
支持三种设备组合：PC→PC（默认）/ PC→Phone / Phone→PC。
"""

import argparse
import os
import sys
import sqlite3

from musicsync.adb_device_kit.cancel_flag import CancelFlag
from musicsync.adb_device_kit.device import Device
from musicsync.adb_device_kit.filter_utils import (
    parse_musicignore,
    DEFAULT_AUDIO_EXTENSIONS,
)
from musicsync.adb_device_kit.executor_helpers import format_size
from musicsync.core.sync_engine import scan, compare
from musicsync.core.executor import execute
from musicsync.store.database import init_db, record_operation, get_setting


def main() -> None:
    # Windows 控制台可能使用 GBK 编码，遇到日文/特殊字符时用替换字符，避免崩溃
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    elif hasattr(sys.stdout, "errors"):
        sys.stdout.errors = "replace"

    parser = argparse.ArgumentParser(
        description="MusicSync — 单向镜像音乐文件夹同步工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python -m musicsync.cli ./Music ./Backup\n"
            "  python -m musicsync.cli --dest-device phone ./Music //sdcard/Music/\n"
            "  python -m musicsync.cli --source-device phone //sdcard/Music/ ./PC_Backup/"
        ),
    )
    parser.add_argument(
        "--source-device",
        choices=["pc", "phone"],
        default="pc",
        help="源端设备类型（默认: pc）",
    )
    parser.add_argument(
        "--dest-device",
        choices=["pc", "phone"],
        default="pc",
        help="目的端设备类型（默认: pc）",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="跳过确认提示（非交互模式）",
    )
    parser.add_argument(
        "source",
        help="源根路径",
    )
    parser.add_argument(
        "dest",
        help="目的根路径",
    )
    args = parser.parse_args()

    source_root: str = args.source
    dest_root: str = args.dest
    is_source_phone = args.source_device == "phone"
    is_dest_phone = args.dest_device == "phone"

    # ── 设备检测与构造 ───────────────────────────────────────
    source_device = _maybe_connect(is_source_phone, "源端")
    dest_device = _maybe_connect(is_dest_phone, "目的端")

    # ── PC 端路径校验 ───────────────────────────────────────
    if not is_source_phone and not os.path.isdir(source_root):
        print(f"错误: 源目录不存在 — {source_root}")
        sys.exit(1)
    if not is_dest_phone and not os.path.isdir(dest_root):
        print(f"错误: 目的目录不存在 — {dest_root}")
        sys.exit(1)

    # ── 加载设置 ──────────────────────────────────────────
    conn = sqlite3.connect("musicsync.db")
    init_db(conn)

    extensions_str = get_setting(conn, "audio_extensions")
    extensions = _parse_extensions(extensions_str)

    # ── 加载 .musicignore（仅 PC 源端） ───────────────────
    musicignore_rules = _load_musicignore(source_root) if not is_source_phone else None

    # ── 设备标签 ──────────────────────────────────────────
    source_label = "Phone" if is_source_phone else "PC"
    dest_label = "Phone" if is_dest_phone else "PC"

    # ── 扫描 ─────────────────────────────────────────────
    cancel_flag = CancelFlag()
    print(f"\nMusicSync — {source_label}→{dest_label} 单向镜像同步")
    print(f"源:   {source_root}")
    print(f"目的: {dest_root}\n")

    print("[扫描源端...]", end=" ")
    source_files, src_skipped = scan(
        source_root, extensions, musicignore_rules,
        device=source_device, cancel_flag=cancel_flag,
    )
    print(f"找到 {len(source_files)} 个文件", end="")
    if src_skipped.total:
        print(f"（跳过 {src_skipped.total} 个非音频）", end="")
    print()

    print("[扫描目的端...]", end=" ")
    dest_files, dst_skipped = scan(
        dest_root, extensions, musicignore_rules=None,
        device=dest_device, cancel_flag=cancel_flag,
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

    if not args.yes:
        try:
            ans = input("\n确认执行？(y/n): ").strip().lower()
        except EOFError:
            print("非交互模式下请使用 --yes 参数。")
            conn.close()
            sys.exit(1)
        if ans != "y":
            print("已取消。")
            conn.close()
            return

    # ── 执行 ─────────────────────────────────────────────
    print()
    result = execute(
        diffs, source_root, dest_root,
        source_device=source_device,
        dest_device=dest_device,
        cancel_flag=cancel_flag,
    )

    # 仅成功的操作写入历史
    src_label = "PC" if args.source_device == "pc" else "Phone"
    dst_label = "PC" if args.dest_device == "pc" else "Phone"
    failed_paths = {f[0] for f in result.failures}
    for d in diffs:
        if d.selected and d.relative_path not in failed_paths:
            if d.operation == "delete":
                direction = dst_label
            else:
                direction = f"{src_label} → {dst_label}"
            record_operation(
                conn,
                action_type=d.operation,
                direction=direction,
                relative_path=d.relative_path,
                file_size=d.source_size or d.dest_size or 0,
                dest_size=d.dest_size if d.operation == "overwrite" else None,
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
# 设备连接辅助
# ---------------------------------------------------------------------------

def _maybe_connect(wanted: bool, label: str) -> Device | None:
    """如果需要 Phone 设备，检测并返回 Device 实例；否则返回 None。"""
    if not wanted:
        return None
    device = Device("adb")
    if device.detect():
        print(f"[{label}] ADB 设备已检测到")
        return device
    else:
        print(f"错误: {label} 需要 Phone 设备，但未检测到已授权的 ADB 设备。")
        print("请确保:")
        print("  1. 手机通过 USB 连接到电脑")
        print("  2. 手机已开启「开发者选项」→「USB 调试」")
        print("  3. 电脑上 `adb devices` 显示设备为 \"device\" 状态")
        sys.exit(1)


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
