from dataclasses import dataclass

from assistant.core.sessions import now_iso
from assistant.storage.db import Database


@dataclass
class Memory:
    id: int
    type: str
    content: str
    tags: str | None
    importance: float
    created_at: str
    last_accessed_at: str | None
    access_count: int
    source_session: str | None


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    def add(self, type: str, content: str, tags: str | None = None,
            importance: float = 0.5, source_session: str | None = None) -> int:
        mid = self.db.execute(
            "INSERT INTO memories (type, content, tags, importance, "
            "created_at, access_count, source_session) "
            "VALUES (?, ?, ?, ?, ?, 0, ?)",
            (type, content, tags, importance, now_iso(), source_session))
        self.db.execute(
            "INSERT INTO memories_fts (rowid, content) VALUES (?, ?)",
            (mid, content))
        return mid

    def get(self, memory_id: int) -> Memory | None:
        row = self.db.query_one(
            "SELECT * FROM memories WHERE id=?", (memory_id,))
        return Memory(**dict(row)) if row else None

    def list_all(self) -> list[Memory]:
        rows = self.db.query("SELECT * FROM memories ORDER BY id")
        return [Memory(**dict(r)) for r in rows]

    def delete(self, memory_id: int) -> None:
        self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self.db.execute(
            "DELETE FROM memories_fts WHERE rowid=?", (memory_id,))

    def clear(self) -> None:
        self.db.execute("DELETE FROM memories")
        self.db.execute("DELETE FROM memories_fts")

    def export(self) -> list[dict]:
        return [dict(r) for r in self.db.query(
            "SELECT type, content, tags, importance, created_at "
            "FROM memories ORDER BY id")]

    def touch(self, memory_id: int) -> None:
        self.db.execute(
            "UPDATE memories SET last_accessed_at=?, access_count=access_count+1 "
            "WHERE id=?", (now_iso(), memory_id))
