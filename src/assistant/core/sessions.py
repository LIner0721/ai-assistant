from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from assistant.providers.base import ChatMessage
from assistant.storage.db import Database


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Session:
    id: str
    title: str
    created_at: str
    updated_at: str


class SessionManager:
    def __init__(self, db: Database):
        self.db = db

    def create(self, title: str = "新会话") -> str:
        sid = uuid.uuid4().hex
        ts = now_iso()
        self.db.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)", (sid, title, ts, ts))
        return sid

    def list(self) -> list[Session]:
        rows = self.db.query(
            "SELECT * FROM sessions ORDER BY updated_at DESC")
        return [Session(**dict(r)) for r in rows]

    def rename(self, session_id: str, title: str) -> None:
        self.db.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
            (title, now_iso(), session_id))

    def delete(self, session_id: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def add_message(self, session_id: str, role: str, content: str) -> None:
        self.db.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)", (session_id, role, content, now_iso()))
        self.db.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?",
            (now_iso(), session_id))

    def history(self, session_id: str) -> list[ChatMessage]:
        rows = self.db.query(
            "SELECT role, content FROM messages WHERE session_id=? "
            "ORDER BY id", (session_id,))
        return [ChatMessage(role=r["role"], content=r["content"]) for r in rows]

    def search(self, query: str) -> list[Session]:
        like = f"%{query}%"
        rows = self.db.query(
            "SELECT DISTINCT s.* FROM sessions s "
            "LEFT JOIN messages m ON m.session_id = s.id "
            "WHERE s.title LIKE ? OR m.content LIKE ? "
            "ORDER BY s.updated_at DESC", (like, like))
        return [Session(**dict(r)) for r in rows]
