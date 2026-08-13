from assistant.memory.extract import MemoryCandidate
from assistant.memory.store import MemoryStore

SIMILARITY_THRESHOLD = 0.35


def _bigrams(text: str) -> set[str]:
    return {text[i:i + 2] for i in range(len(text) - 1)} or {text}


def _jaccard(a: str, b: str) -> float:
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class MemoryResolver:
    """去重与冲突消解：相似内容更新旧记忆，避免重复沉淀。"""

    def __init__(self, store: MemoryStore):
        self.store = store

    def apply(self, candidates: list[MemoryCandidate],
              source_session: str | None = None) -> list[int]:
        ids: list[int] = []
        for cand in candidates:
            best_id, best_score = None, 0.0
            for existing in self.store.list_all():
                score = _jaccard(cand.content, existing.content)
                if score > best_score:
                    best_id, best_score = existing.id, score
            if best_id is not None and best_score >= SIMILARITY_THRESHOLD:
                self._update(best_id, cand.content)
                ids.append(best_id)
            else:
                ids.append(self.store.add(
                    cand.type, cand.content,
                    importance=cand.importance,
                    source_session=source_session))
        return ids

    def _update(self, memory_id: int, content: str) -> None:
        self.store.db.execute(
            "UPDATE memories SET content=? WHERE id=?", (content, memory_id))
        self.store.db.execute(
            "UPDATE memories_fts SET content=? WHERE rowid=?",
            (content, memory_id))
