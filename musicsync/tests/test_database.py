"""test_database.py — store/database.py 的单元测试（SQLite :memory:）。"""

import sqlite3
import pytest
from musicsync.store.database import (
    init_db, record_operation, list_operations, list_operations_filtered,
    get_setting, set_setting,
)


class TestInitDb:
    """init_db() 建表测试。"""

    def test_creates_tables_idempotent(self):
        """init_db 应幂等创建 operation_history 和 app_settings 两张表。"""
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")

        init_db(conn)
        # 验证表存在
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "operation_history" in table_names
        assert "app_settings" in table_names

        # 幂等：重复调用不报错
        init_db(conn)

        conn.close()

    def test_app_settings_defaults(self):
        """init_db 应将 audio_extensions 默认值写入 app_settings。"""
        conn = sqlite3.connect(":memory:")
        init_db(conn)
        value = conn.execute(
            "SELECT value FROM app_settings WHERE key='audio_extensions'"
        ).fetchone()
        assert value is not None
        conn.close()


class TestRecordOperation:
    """record_operation() 测试。"""

    def setup_method(self):
        self.conn = sqlite3.connect(":memory:")
        init_db(self.conn)

    def teardown_method(self):
        self.conn.close()

    def test_insert_and_return_id(self):
        """插入操作记录应返回自增 ID。"""
        op_id = record_operation(
            self.conn,
            action_type="copy",
            direction="PC → Phone",
            relative_path="VOCALOID/song.flac",
            file_size=26580279,
        )
        assert op_id is not None
        assert isinstance(op_id, int)
        assert op_id >= 1

    def test_all_action_types_allowed(self):
        """copy、overwrite、delete 三种 action_type 都可以插入。"""
        test_cases = [
            ("copy", "PC → Phone", 1000, None),
            ("overwrite", "PC → PC", 2000, 1500),
            ("delete", "Phone", 3000, None),
        ]
        for action, direction, file_size, dest_size in test_cases:
            op_id = record_operation(
                self.conn,
                action_type=action,
                direction=direction,
                relative_path=f"{action}/test.flac",
                file_size=file_size,
                dest_size=dest_size,
            )
            assert op_id is not None

    def test_invalid_action_type_rejected(self):
        """非法 action_type 应被 CHECK 约束拒绝。"""
        with pytest.raises(sqlite3.IntegrityError):
            record_operation(
                self.conn,
                action_type="invalid_action",
                direction="PC → Phone",
                relative_path="test.flac",
                file_size=1000,
            )

    def test_record_has_timestamp(self):
        """插入的记录应包含 UTC 时区的 ISO 8601 时间戳。"""
        op_id = record_operation(
            self.conn,
            action_type="delete",
            direction="Phone",
            relative_path="Trash/tmp.mp3",
            file_size=3200,
        )
        row = self.conn.execute(
            "SELECT timestamp FROM operation_history WHERE id=?", (op_id,)
        ).fetchone()
        assert row is not None
        assert row[0]  # 非空字符串
        # 应为 ISO 8601 格式
        assert "T" in row[0]

    def test_overwrite_records_dest_size(self):
        """overwrite 操作应记录 dest_size（目的端旧大小）。"""
        op_id = record_operation(
            self.conn,
            action_type="overwrite",
            direction="PC → Phone",
            relative_path="Rock/song.flac",
            file_size=26580279,
            dest_size=12345678,
        )
        row = self.conn.execute(
            "SELECT file_size, dest_size FROM operation_history WHERE id=?", (op_id,)
        ).fetchone()
        assert row[0] == 26580279  # 源端新大小
        assert row[1] == 12345678  # 目的端旧大小

    def test_copy_dest_size_null(self):
        """copy 操作的 dest_size 应为 NULL。"""
        op_id = record_operation(
            self.conn,
            action_type="copy",
            direction="PC → Phone",
            relative_path="New/song.flac",
            file_size=5000000,
        )
        row = self.conn.execute(
            "SELECT dest_size FROM operation_history WHERE id=?", (op_id,)
        ).fetchone()
        assert row[0] is None

    def test_device_label_direction_formats(self):
        """direction 支持三种设备组合格式 + delete 格式。"""
        formats = [
            "PC → PC",
            "PC → Phone",
            "Phone → PC",
            "PC",       # delete
            "Phone",    # delete
        ]
        for direction in formats:
            op_id = record_operation(
                self.conn,
                action_type="copy" if "→" in direction else "delete",
                direction=direction,
                relative_path="test.flac",
                file_size=1000,
            )
            row = self.conn.execute(
                "SELECT direction FROM operation_history WHERE id=?", (op_id,)
            ).fetchone()
            assert row[0] == direction


class TestListOperations:
    """list_operations() 测试。"""

    def setup_method(self):
        self.conn = sqlite3.connect(":memory:")
        init_db(self.conn)

    def teardown_method(self):
        self.conn.close()

    def test_empty_returns_empty_list(self):
        """无记录时应返回空列表。"""
        result = list_operations(self.conn)
        assert result == []

    def test_returns_all_records_ordered_by_time_desc(self):
        """应按时间倒序返回所有记录。"""
        # 插入多条
        ids = []
        for i in range(5):
            op_id = record_operation(
                self.conn,
                action_type="copy",
                direction="source → dest",
                relative_path=f"Track{i}.flac",
                file_size=1000 + i,
            )
            ids.append(op_id)

        result = list_operations(self.conn)
        assert len(result) == 5
        # 时间倒序：最新先
        assert result[0]["id"] == ids[-1]
        assert result[-1]["id"] == ids[0]

    def test_respects_limit(self):
        """limit 参数应限制返回数量。"""
        for i in range(10):
            record_operation(
                self.conn,
                action_type="copy",
                direction="source → dest",
                relative_path=f"Track{i}.flac",
                file_size=1000,
            )

        result = list_operations(self.conn, limit=3)
        assert len(result) == 3

    def test_returns_dicts_with_all_fields(self):
        """返回的每条记录应包含所有必需字段。"""
        op_id = record_operation(
            self.conn,
            action_type="overwrite",
            direction="PC → Phone",
            relative_path="Album/song.mp3",
            file_size=15200000,
            dest_size=8800000,
        )
        result = list_operations(self.conn, limit=1)
        record = result[0]
        assert record["id"] == op_id
        assert record["action_type"] == "overwrite"
        assert record["direction"] == "PC → Phone"
        assert record["relative_path"] == "Album/song.mp3"
        assert record["file_size"] == 15200000
        assert record["dest_size"] == 8800000
        assert record["timestamp"].endswith("+00:00")


class TestSettings:
    """get_setting() / set_setting() 测试。"""

    def setup_method(self):
        self.conn = sqlite3.connect(":memory:")
        init_db(self.conn)

    def teardown_method(self):
        self.conn.close()

    def test_get_existing_key(self):
        """读取已存在的设置键。"""
        value = get_setting(self.conn, "audio_extensions")
        assert value is not None
        assert "flac" in value

    def test_get_missing_key_returns_none(self):
        """读取不存在的键返回 None。"""
        value = get_setting(self.conn, "nonexistent_key")
        assert value is None

    def test_set_new_key(self):
        """设置新键值对。"""
        set_setting(self.conn, "musicignore_enabled", "true")
        value = get_setting(self.conn, "musicignore_enabled")
        assert value == "true"

    def test_set_overwrites_existing(self):
        """设置已有键应覆盖旧值。"""
        set_setting(self.conn, "audio_extensions", '["flac","mp3"]')
        value = get_setting(self.conn, "audio_extensions")
        assert value == '["flac","mp3"]'


class TestListOperationsFiltered:
    """list_operations_filtered() 分页+筛选测试。"""

    def setup_method(self):
        self.conn = sqlite3.connect(":memory:")
        init_db(self.conn)

    def teardown_method(self):
        self.conn.close()

    def _insert_batch(self, count: int, base_ts: str = "2026-07-23T"):
        """批量插入测试数据，时间戳均匀分布在 24 小时内。"""
        for i in range(count):
            hour = f"{i % 24:02d}"
            ts = f"{base_ts}{hour}:00:00+00:00"
            self.conn.execute(
                """INSERT INTO operation_history
                   (action_type, direction, relative_path, file_size, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                ("copy", "PC → Phone", f"Track{i:04d}.flac", 1000 + i, ts),
            )
        self.conn.commit()

    def _insert_multi_day(self):
        """插入跨多天的测试数据。"""
        dates = [
            "2026-07-23T10:00:00+00:00",
            "2026-07-23T14:00:00+00:00",
            "2026-07-22T08:00:00+00:00",
            "2026-07-21T20:00:00+00:00",
            "2026-07-20T06:00:00+00:00",
        ]
        for i, ts in enumerate(dates):
            self.conn.execute(
                """INSERT INTO operation_history
                   (action_type, direction, relative_path, file_size, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                ("copy", "PC → Phone", f"Day{i}.flac", 1000 + i, ts),
            )
        self.conn.commit()

    # ── 分页 ──

    def test_empty_returns_empty(self):
        """无记录时应返回空列表和 total=0。"""
        records, total = list_operations_filtered(self.conn, page=1, page_size=30)
        assert records == []
        assert total == 0

    def test_single_page_all_returned(self):
        """数据量小于 page_size 时应全部返回。"""
        self._insert_batch(20)
        records, total = list_operations_filtered(self.conn, page=1, page_size=30)
        assert len(records) == 20
        assert total == 20

    def test_multi_page(self):
        """第 2 页应返回正确的 30 条记录。"""
        self._insert_batch(100)
        records, total = list_operations_filtered(self.conn, page=2, page_size=30)
        assert len(records) == 30
        assert total == 100

    def test_last_page_partial(self):
        """最后一页不足 page_size 时应返回剩余条数。"""
        self._insert_batch(100)
        records, total = list_operations_filtered(self.conn, page=4, page_size=30)
        assert len(records) == 10
        assert total == 100

    def test_page_beyond_range(self):
        """超出页码范围返回空列表但 total 不变。"""
        self._insert_batch(100)
        records, total = list_operations_filtered(self.conn, page=999, page_size=30)
        assert records == []
        assert total == 100

    def test_page_clamped_to_1(self):
        """page <= 0 时自动 clamp 到第 1 页。"""
        self._insert_batch(20)
        records, _ = list_operations_filtered(self.conn, page=0, page_size=30)
        assert len(records) == 20

    # ── 排序 ──

    def test_order_desc_by_timestamp_and_id(self):
        """应按 timestamp DESC, id DESC 排序。"""
        # 同秒插入多条（id 递增）
        for i in range(5):
            self.conn.execute(
                """INSERT INTO operation_history
                   (action_type, direction, relative_path, file_size, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                ("copy", "PC → Phone", f"Same{i}.flac", i,
                 "2026-07-23T12:00:00+00:00"),
            )
        self.conn.commit()
        records, _ = list_operations_filtered(self.conn, page=1, page_size=30)
        # 同秒：id 大的在前
        ids = [r["id"] for r in records]
        assert ids == sorted(ids, reverse=True)

    # ── 日期筛选 ──

    def test_date_from_filter(self):
        """date_from 应筛选 timestamp >= 指定值。"""
        self._insert_multi_day()
        # 筛选 7/22 及之后（UTC 下界 = 7/22 00:00）
        records, total = list_operations_filtered(
            self.conn, page=1, page_size=30,
            date_from="2026-07-22T00:00:00+00:00",
        )
        # 应包含 7/22、7/23（3 条）
        assert total == 3
        timestamps = [r["timestamp"] for r in records]
        for ts in timestamps:
            assert ts >= "2026-07-22T00:00:00+00:00"

    def test_date_to_filter_exclusive(self):
        """date_to 应筛选 timestamp < 指定值（开区间）。"""
        self._insert_multi_day()
        # 筛选 7/21 之前（不含 7/21）
        records, total = list_operations_filtered(
            self.conn, page=1, page_size=30,
            date_to="2026-07-21T00:00:00+00:00",
        )
        # 应只含 7/20（1 条）
        assert total == 1
        assert records[0]["timestamp"] < "2026-07-21T00:00:00+00:00"

    def test_date_range(self):
        """组合 date_from + date_to 应正确筛选闭开区间。"""
        self._insert_multi_day()
        records, total = list_operations_filtered(
            self.conn, page=1, page_size=30,
            date_from="2026-07-21T00:00:00+00:00",
            date_to="2026-07-23T00:00:00+00:00",
        )
        # 7/21 + 7/22 = 2 条
        assert total == 2

    # ── 搜索筛选 ──

    def test_search_filter(self):
        """搜索应模糊匹配 relative_path。"""
        for name in ["song.flac", "SONG2.mp3", "other.wav", "mysong.aac"]:
            self.conn.execute(
                """INSERT INTO operation_history
                   (action_type, direction, relative_path, file_size, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                ("copy", "PC → Phone", name, 1000,
                 "2026-07-23T12:00:00+00:00"),
            )
        self.conn.commit()
        records, total = list_operations_filtered(
            self.conn, page=1, page_size=30, search="song",
        )
        # LIKE 默认不区分大小写（SQLite LIKE 对 ASCII 不区分）
        assert total >= 2  # song.flac + mysong.aac（SONG2.mp3 也匹配因为不区分）

    def test_search_empty_is_none(self):
        """空字符串搜索应等同于 None（无筛选）。"""
        self._insert_batch(20)
        records1, total1 = list_operations_filtered(
            self.conn, page=1, page_size=30, search="",
        )
        records2, total2 = list_operations_filtered(
            self.conn, page=1, page_size=30, search=None,
        )
        assert total1 == total2 == 20

    # ── 组合筛选 ──

    def test_combined_filters(self):
        """日期 + 搜索组合应 AND 取交集。"""
        self._insert_multi_day()
        # Day4 是 7/20 的记录，date_from=7/22 会筛掉它
        records, total = list_operations_filtered(
            self.conn, page=1, page_size=30,
            date_from="2026-07-22T00:00:00+00:00",
            search="Day4",
        )
        # Day4 在 7/20，不在 date_from 范围内 → 0 条
        assert total == 0

    # ── total_count 不受分页影响 ──

    def test_total_count_exceeds_page(self):
        """total_count 反映全部匹配数，不受 LIMIT/OFFSET 限制。"""
        self._insert_batch(100)
        _, total_page1 = list_operations_filtered(
            self.conn, page=1, page_size=30,
        )
        _, total_page3 = list_operations_filtered(
            self.conn, page=3, page_size=30,
        )
        assert total_page1 == 100
        assert total_page3 == 100

    # ── 返回格式 ──

    def test_returns_dicts_with_all_fields(self):
        """返回 dict 应包含全部字段且 timestamp 含 UTC 后缀。"""
        op_id = record_operation(
            self.conn,
            action_type="overwrite",
            direction="PC → Phone",
            relative_path="Album/song.mp3",
            file_size=15200000,
            dest_size=8800000,
        )
        records, total = list_operations_filtered(self.conn, page=1, page_size=30)
        assert total == 1
        r = records[0]
        assert r["id"] == op_id
        assert r["action_type"] == "overwrite"
        assert r["direction"] == "PC → Phone"
        assert r["relative_path"] == "Album/song.mp3"
        assert r["file_size"] == 15200000
        assert r["dest_size"] == 8800000
        assert "+00:00" in r["timestamp"]
