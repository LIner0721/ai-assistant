import math
from datetime import datetime, timezone

from assistant.memory.store import Memory, MemoryStore


def _days_since(iso: str) -> float:
    created = datetime.fromisoformat(iso)
    now = datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max((now - created).total_seconds() / 86400.0, 0.0)


class MemoryRetriever:
    def __init__(self, store: MemoryStore, k: int = 8):
        self.store = store
        self.k = k

    def retrieve(self, query: str, k: int | None = None) -> list[Memory]:
        k = k or self.k
        matched_ids: set[int] = set()
        q = query.strip()
        if q:
            # FTS5 trigram 需 ≥3 字符；更短的中文词用 LIKE 子串回退
            if len(q) >= 3:
                rows = self.store.db.query(
                    "SELECT rowid FROM memories_fts WHERE content MATCH ? "
                    "LIMIT 50", (q,))
                matched_ids = {r["rowid"] for r in rows}
            else:
                rows = self.store.db.query(
                    "SELECT id FROM memories WHERE content LIKE ? "
                    "LIMIT 50", (f"%{q}%",))
                matched_ids = {r["id"] for r in rows}

        ranked: list[tuple[float, Memory]] = []
        for m in self.store.list_all():
            score = (1.0 if m.id in matched_ids else 0.0)
            score += m.importance
            score += min(m.access_count, 10) * 0.05
            score += math.exp(-_days_since(m.created_at) / 30.0)
            ranked.append((score, m))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        top = [m for _, m in ranked[:k]]
        for m in top:
            self.store.touch(m.id)
        return top
