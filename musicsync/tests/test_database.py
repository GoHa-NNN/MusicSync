"""test_database.py — store/database.py 的单元测试（SQLite :memory:）。"""

import sqlite3
import pytest
from musicsync.store.database import init_db, record_operation, list_operations, get_setting, set_setting


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
            direction="source → dest",
            relative_path="VOCALOID/song.flac",
            file_size=26580279,
        )
        assert op_id is not None
        assert isinstance(op_id, int)
        assert op_id >= 1

    def test_all_action_types_allowed(self):
        """copy、overwrite、delete 三种 action_type 都可以插入。"""
        for action in ("copy", "overwrite", "delete"):
            op_id = record_operation(
                self.conn,
                action_type=action,
                direction="source → dest",
                relative_path=f"{action}/test.flac",
                file_size=1000,
            )
            assert op_id is not None

    def test_invalid_action_type_rejected(self):
        """非法 action_type 应被 CHECK 约束拒绝。"""
        with pytest.raises(sqlite3.IntegrityError):
            record_operation(
                self.conn,
                action_type="invalid_action",
                direction="source → dest",
                relative_path="test.flac",
                file_size=1000,
            )

    def test_record_has_timestamp(self):
        """插入的记录应包含时间戳。"""
        op_id = record_operation(
            self.conn,
            action_type="delete",
            direction="dest",
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
            direction="source → dest",
            relative_path="Album/song.mp3",
            file_size=15200000,
        )
        result = list_operations(self.conn, limit=1)
        record = result[0]
        assert record["id"] == op_id
        assert record["action_type"] == "overwrite"
        assert record["direction"] == "source → dest"
        assert record["relative_path"] == "Album/song.mp3"
        assert record["file_size"] == 15200000
        assert "timestamp" in record


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
