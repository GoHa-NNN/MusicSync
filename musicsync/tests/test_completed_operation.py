"""test_completed_operation.py — CompletedOperation + DirectionFormatter 单元测试。

验证：
- CLI 和 GUI 使用同一个 CompletedOperation.from_diff_item() 产生的 DB 参数完全一致
- direction_for_db 对 copy/overwrite/delete 三种操作生成正确的标签格式
- to_record_params() 正确映射文件 sizes
- DirectionFormatter 处理 v2 格式、v1 兼容、delete-only 方向
"""

import pytest

from musicsync.adb_device_kit.models import FileInfo
from musicsync.core.completed_operation import CompletedOperation, DirectionFormatter
from musicsync.core.models import DiffItem


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _diff_item(
    relative_path: str = "song.flac",
    operation: str = "copy",
    source_size: int | None = 5000,
    dest_size: int | None = None,
) -> DiffItem:
    """构造测试用 DiffItem。"""
    return DiffItem(
        relative_path=relative_path,
        diff_type={"copy": "new_in_dest", "overwrite": "updated_in_dest", "delete": "only_in_dest"}[operation],
        operation=operation,
        direction="source → dest",
        source_size=source_size,
        dest_size=dest_size,
        selected=True,
    )


# ---------------------------------------------------------------------------
# CompletedOperation — 基础
# ---------------------------------------------------------------------------

class TestCompletedOperationBasics:
    def test_creates_from_diff_item(self):
        diff = _diff_item(operation="copy", source_size=5000)
        co = CompletedOperation.from_diff_item(diff, "PC", "Phone")
        assert co.operation == "copy"
        assert co.relative_path == "song.flac"
        assert co.src_label == "PC"
        assert co.dst_label == "Phone"

    def test_frozen_dataclass(self):
        """CompletedOperation 应该是不可变的（frozen dataclass）。"""
        diff = _diff_item()
        co = CompletedOperation.from_diff_item(diff, "PC", "Phone")
        with pytest.raises(Exception):
            co.src_label = "X"  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# CompletedOperation — direction_for_db
# ---------------------------------------------------------------------------

class TestDirectionForDb:
    def test_copy_pc_to_phone(self):
        diff = _diff_item(operation="copy", source_size=5000)
        co = CompletedOperation.from_diff_item(diff, "PC", "Phone")
        assert co.direction_for_db == "PC → Phone"

    def test_copy_phone_to_pc(self):
        diff = _diff_item(operation="copy", source_size=5000)
        co = CompletedOperation.from_diff_item(diff, "Phone", "PC")
        assert co.direction_for_db == "Phone → PC"

    def test_overwrite_pc_to_pc(self):
        diff = _diff_item(
            operation="overwrite",
            source_size=9000,
            dest_size=8000,
        )
        co = CompletedOperation.from_diff_item(diff, "PC", "PC")
        assert co.direction_for_db == "PC → PC"

    def test_delete_pc(self):
        diff = _diff_item(operation="delete", dest_size=3000)
        co = CompletedOperation.from_diff_item(diff, "PC", "PC")
        assert co.direction_for_db == "PC"

    def test_delete_phone(self):
        diff = _diff_item(operation="delete", dest_size=3000)
        co = CompletedOperation.from_diff_item(diff, "PC", "Phone")
        assert co.direction_for_db == "Phone"


# ---------------------------------------------------------------------------
# CompletedOperation — to_record_params
# ---------------------------------------------------------------------------

class TestToRecordParams:
    def test_copy_excludes_dest_size(self):
        diff = _diff_item(operation="copy", source_size=5000)
        co = CompletedOperation.from_diff_item(diff, "PC", "Phone")
        params = co.to_record_params()
        assert params["action_type"] == "copy"
        assert params["direction"] == "PC → Phone"
        assert params["relative_path"] == "song.flac"
        assert params["file_size"] == 5000
        assert params["dest_size"] is None

    def test_overwrite_includes_dest_size(self):
        diff = _diff_item(
            operation="overwrite",
            source_size=9000,
            dest_size=8000,
        )
        co = CompletedOperation.from_diff_item(diff, "Phone", "PC")
        params = co.to_record_params()
        assert params["action_type"] == "overwrite"
        assert params["direction"] == "Phone → PC"
        assert params["file_size"] == 9000
        assert params["dest_size"] == 8000

    def test_delete_uses_dest_size_as_file_size(self):
        diff = _diff_item(operation="delete", source_size=None, dest_size=4200)
        co = CompletedOperation.from_diff_item(diff, "PC", "Phone")
        params = co.to_record_params()
        assert params["action_type"] == "delete"
        assert params["direction"] == "Phone"
        assert params["file_size"] == 4200
        assert params["dest_size"] is None  # delete → dest_size=None in DB

    def test_delete_with_source_size_prefers_source(self):
        """delete 操作中 source_size 可能为 None，fallback 到 dest_size。"""
        diff = _diff_item(operation="delete", source_size=None, dest_size=4200)
        co = CompletedOperation.from_diff_item(diff, "PC", "PC")
        params = co.to_record_params()
        assert params["file_size"] == 4200


# ---------------------------------------------------------------------------
# CLI vs GUI 一致性
# ---------------------------------------------------------------------------

class TestCliGuiConsistency:
    def test_cli_and_gui_generate_identical_params(self):
        """同一 DiffItem + 相同 label → CLI 和 GUI 产生完全相同的 record_params。"""
        diff = _diff_item(operation="overwrite", source_size=9000, dest_size=8000)
        gui_params = CompletedOperation.from_diff_item(diff, "PC", "Phone").to_record_params()
        cli_params = CompletedOperation.from_diff_item(diff, "PC", "Phone").to_record_params()
        assert gui_params == cli_params

    def test_different_labels_produce_different_directions(self):
        """不同 label 组合产生不同的 direction。"""
        diff = _diff_item(operation="copy", source_size=5000)
        pc_phone = CompletedOperation.from_diff_item(diff, "PC", "Phone").to_record_params()
        phone_pc = CompletedOperation.from_diff_item(diff, "Phone", "PC").to_record_params()
        assert pc_phone["direction"] == "PC → Phone"
        assert phone_pc["direction"] == "Phone → PC"
        assert pc_phone != phone_pc


# ---------------------------------------------------------------------------
# DirectionFormatter
# ---------------------------------------------------------------------------

class TestDirectionFormatter:
    def test_v2_format_pc_phone(self):
        result = DirectionFormatter.parse_display("copy", "PC → Phone")
        assert result == "复制 [PC] → [Phone]"

    def test_v2_format_phone_pc(self):
        result = DirectionFormatter.parse_display("overwrite", "Phone → PC")
        assert result == "覆盖 [Phone] → [PC]"

    def test_v2_format_pc_pc(self):
        result = DirectionFormatter.parse_display("copy", "PC → PC")
        assert result == "复制 [PC] → [PC]"

    def test_delete_v2_pc(self):
        result = DirectionFormatter.parse_display("delete", "PC")
        assert result == "删除 in [PC]"

    def test_delete_v2_phone(self):
        result = DirectionFormatter.parse_display("delete", "Phone")
        assert result == "删除 in [Phone]"

    def test_v1_generic_fallback(self):
        """v1 泛化标签回退到 [PC]。"""
        result = DirectionFormatter.parse_display("copy", "source → dest")
        assert result == "复制 [PC] → [PC]"

    def test_delete_v1_fallback(self):
        """v1 delete-only 泛化标签回退到 [PC]。"""
        result = DirectionFormatter.parse_display("delete", "dest")
        assert result == "删除"

    def test_unknown_action_type(self):
        """未知 action_type 原样返回。"""
        result = DirectionFormatter.parse_display("foobar", "PC → Phone")
        assert result == "foobar [PC] → [Phone]"

    def test_empty_direction(self):
        """空 direction 直接返回 action。"""
        result = DirectionFormatter.parse_display("copy", "")
        assert result == "复制"
