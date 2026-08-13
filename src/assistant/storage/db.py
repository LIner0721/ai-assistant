import sqlite3
from pathlib import Path

MIGRATIONS: list[str] = [
    # v1: 初始 schema
    """
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE task_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        step_no INTEGER NOT NULL,
        tool TEXT,
        args TEXT,
        result TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        content TEXT NOT NULL,
        tags TEXT,
        importance REAL NOT NULL DEFAULT 0.5,
        created_at TEXT NOT NULL,
        last_accessed_at TEXT,
        access_count INTEGER NOT NULL DEFAULT 0,
        source_session TEXT
    );
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # v2: 记忆全文索引（trigram 分词，中文友好）
    """
    CREATE VIRTUAL TABLE memories_fts USING fts5(
        content, tokenize='trigram'
    );
    """,
]


class Database:
    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def migrate(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        current = self.schema_version()
        for i, sql in enumerate(MIGRATIONS, start=1):
            if i <= current:
                continue
            self._conn.executescript(sql)
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (i,))
            self._conn.commit()

    def schema_version(self) -> int:
        row = self._conn.execute(
            "SELECT MAX(version) AS v FROM schema_version").fetchone()
        return int(row["v"]) if row and row["v"] is not None else 0

    def execute(self, sql: str, params: tuple = ()) -> int:
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur.lastrowid or 0

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self._conn.execute(sql, params))

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
