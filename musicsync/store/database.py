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
    # 迁移 v2：增加 dest_size 列（v1 无此列，对所有现有记录填 NULL）
    try:
        conn.execute(
            "ALTER TABLE operation_history ADD COLUMN dest_size INTEGER"
        )
    except sqlite3.OperationalError:
        pass  # 列已存在
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS remembered_paths (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            device_type TEXT NOT NULL CHECK(device_type IN ('pc','phone')),
            path        TEXT NOT NULL,
            role        TEXT NOT NULL CHECK(role IN ('source','dest')),
            last_used   TEXT NOT NULL,
            UNIQUE(device_type, path, role)
        )
    """)
    conn.commit()


def record_operation(
    conn: sqlite3.Connection,
    action_type: str,
    direction: str,
    relative_path: str,
    file_size: int,
    dest_size: int | None = None,
) -> int:
    """插入一条操作记录，返回自增 ID。

    Args:
        conn: 数据库连接
        action_type: ``"copy"`` / ``"overwrite"`` / ``"delete"``
        direction: 操作方向描述，含设备标签，如 ``"PC → Phone"`` / ``"Phone"``
        relative_path: 文件相对路径
        file_size: 源端文件大小（字节），delete 操作时为被删文件大小
        dest_size: 目的端文件大小（字节），copy 时为 None，overwrite 时为旧大小

    Returns:
        新插入记录的自增 ID
    """
    timestamp = datetime.now(timezone.utc).isoformat()  # UTC 存储，显示时转本地
    cursor = conn.execute(
        """INSERT INTO operation_history
           (action_type, direction, relative_path, file_size, dest_size, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (action_type, direction, relative_path, file_size, dest_size, timestamp),
    )
    conn.commit()
    return cursor.lastrowid


def list_operations(
    conn: sqlite3.Connection, limit: int = 500
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
        """SELECT id, action_type, direction, relative_path, file_size, dest_size, timestamp
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
            "dest_size": r[5],
            "timestamp": r[6],
        }
        for r in rows
    ]


def list_operations_filtered(
    conn: sqlite3.Connection,
    *,
    page: int = 1,
    page_size: int = 30,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
) -> tuple[list[dict], int]:
    """分页+筛选查询操作记录，按时间降序返回。

    全部参数为 keyword-only。筛选条件以 AND 组合。

    Args:
        conn: 数据库连接
        page: 页码（1-based），不足 1 时 clamp 到 1
        page_size: 每页条数
        date_from: UTC ISO 8601 字符串，闭区间下界（``timestamp >= ?``）
        date_to: UTC ISO 8601 字符串，开区间上界（``timestamp < ?``）
        search: 文件名模糊匹配，对应 ``relative_path LIKE %search%``，
            空字符串或 None 表示不筛选

    Returns:
        ``(records, total_count)`` — records 为 dict 列表（与
        ``list_operations`` 同格式），total_count 为符合筛选条件的总条数
    """
    where_clauses: list[str] = []
    params: list = []

    if date_from is not None:
        where_clauses.append("timestamp >= ?")
        params.append(date_from)

    if date_to is not None:
        where_clauses.append("timestamp < ?")
        params.append(date_to)

    if search:
        where_clauses.append("relative_path LIKE ?")
        params.append(f"%{search}%")

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # 总数（不受分页影响）
    count_params = list(params)
    total = conn.execute(
        f"SELECT COUNT(*) FROM operation_history WHERE {where_sql}",
        count_params,
    ).fetchone()[0]

    # 分页查询
    page = max(page, 1)
    offset = (page - 1) * page_size
    query_params = list(params) + [page_size, offset]
    rows = conn.execute(
        f"""SELECT id, action_type, direction, relative_path, file_size, dest_size, timestamp
            FROM operation_history
            WHERE {where_sql}
            ORDER BY timestamp DESC, id DESC
            LIMIT ? OFFSET ?""",
        query_params,
    ).fetchall()

    records = [
        {
            "id": r[0],
            "action_type": r[1],
            "direction": r[2],
            "relative_path": r[3],
            "file_size": r[4],
            "dest_size": r[5],
            "timestamp": r[6],
        }
        for r in rows
    ]
    return records, total


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


def remember_path(
    conn: sqlite3.Connection,
    device_type: str,
    path: str,
    role: str,
) -> None:
    """插入或更新路径记忆。

    Args:
        conn: 数据库连接
        device_type: ``"pc"`` 或 ``"phone"``
        path: 路径字符串
        role: ``"source"`` 或 ``"dest"``
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO remembered_paths
           (device_type, path, role, last_used)
           VALUES (?, ?, ?, ?)""",
        (device_type, path, role, now),
    )
    conn.commit()


def list_remembered_paths(
    conn: sqlite3.Connection,
    device_type: str,
    role: str,
    limit: int = 10,
) -> list[str]:
    """按最近使用时间倒序返回记忆的路径列表。

    Args:
        conn: 数据库连接
        device_type: ``"pc"`` 或 ``"phone"``
        role: ``"source"`` 或 ``"dest"``
        limit: 最大返回条数

    Returns:
        路径字符串列表（不含 device_type 和 role）
    """
    rows = conn.execute(
        """SELECT path FROM remembered_paths
           WHERE device_type=? AND role=?
           ORDER BY last_used DESC
           LIMIT ?""",
        (device_type, role, limit),
    ).fetchall()
    return [r[0] for r in rows]
