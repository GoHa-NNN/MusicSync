"""SQLite 持久化层 — 建表 + CRUD。

所有函数接受 ``sqlite3.Connection`` 作为第一个参数。
写入函数内部自动调用 ``conn.commit()``，读取函数不提交。
"""

import sqlite3
from datetime import datetime, timezone


def init_db(conn: sqlite3.Connection) -> None:
    """创建数据库表（幂等）。

    两张表：
    - ``operation_history`` — 操作记录（持久）
    - ``app_settings`` — 键值设置（持久），含音频扩展名默认值
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operation_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type   TEXT NOT NULL CHECK(action_type IN ('copy','overwrite','delete')),
            direction     TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            file_size     INTEGER NOT NULL,
            timestamp     TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_op_history_timestamp
            ON operation_history(timestamp DESC)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO app_settings (key, value) VALUES
        ('audio_extensions', '["flac","mp3","wav","aac","ogg","m4a","wma"]')
    """)
    conn.commit()


def record_operation(
    conn: sqlite3.Connection,
    action_type: str,
    direction: str,
    relative_path: str,
    file_size: int,
) -> int:
    """插入一条操作记录，返回自增 ID。

    Args:
        conn: 数据库连接
        action_type: ``"copy"`` / ``"overwrite"`` / ``"delete"``
        direction: 操作方向描述，如 ``"source → dest"``
        relative_path: 文件相对路径
        file_size: 文件大小（字节）

    Returns:
        新插入记录的自增 ID
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """INSERT INTO operation_history
           (action_type, direction, relative_path, file_size, timestamp)
           VALUES (?, ?, ?, ?, ?)""",
        (action_type, direction, relative_path, file_size, timestamp),
    )
    conn.commit()
    return cursor.lastrowid


def list_operations(
    conn: sqlite3.Connection, limit: int = 50
) -> list[dict]:
    """按时间倒序返回操作记录列表。

    Args:
        conn: 数据库连接
        limit: 最大返回条数

    Returns:
        操作记录列表，每条为 dict（id, action_type, direction,
        relative_path, file_size, timestamp）
    """
    rows = conn.execute(
        """SELECT id, action_type, direction, relative_path, file_size, timestamp
           FROM operation_history
           ORDER BY timestamp DESC, id DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "action_type": r[1],
            "direction": r[2],
            "relative_path": r[3],
            "file_size": r[4],
            "timestamp": r[5],
        }
        for r in rows
    ]


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    """读取设置值，键不存在时返回 None。"""
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key=?", (key,)
    ).fetchone()
    return row[0] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """设置键值对，键已存在时覆盖。"""
    conn.execute(
        "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()
