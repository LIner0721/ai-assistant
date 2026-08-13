# Assistant 记忆 + 人设 + 发布 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现长期记忆系统（沉淀/去重消解/检索注入）、人设管理（双人格分离）、记忆管理 UI、托盘/全局热键/开机自启，最终打包为 Windows 单文件 exe 并输出验收清单。

**Architecture:** `memory/` 提供 MemoryStore（SQLite + FTS5 trigram 索引，中文友好）、MemoryRetriever（关键词 + 时间衰减 + 重要度加权）、MemoryExtractor（LLM 提炼）与 MemoryResolver（bigram Jaccard 去重消解）；ChatService 注入记忆并用 PersonaManager 组装 system prompt；托盘/热键走 pynput + QSystemTrayIcon；PyInstaller 单文件打包，chromium 首次运行自动下载。

**Tech Stack:** 复用 Plan 1/2 全部；新增 pyinstaller（dev extra）。

**Spec:** `docs/superpowers/specs/2026-08-13-windows-ai-assistant-design.md`
**依赖计划:** `docs/superpowers/plans/2026-08-13-assistant-platform-and-chat.md`、`docs/superpowers/plans/2026-08-13-assistant-tools-and-agent.md`

## Global Constraints

- Plan 1/2 全部约束继续生效
- 记忆全本地，不引入 embedding；检索器接口预留 embedding 位
- 双人格分离：聊天线用用户人设，任务线用 EXECUTOR_SYSTEM（已实现，勿动）
- 记忆提取在聊天 worker 线程内同步完成（小 LLM 调用），失败静默不影响聊天
- Windows 专属功能（开机自启 winreg、DPAPI）必须延迟导入并在非 Windows 环境安全降级
- 每任务 commit

---

### Task 1: MemoryStore（迁移 v2 + FTS5 trigram）

**Files:**
- Modify: `src/assistant/storage/db.py`（追加 MIGRATIONS v2）
- Create: `src/assistant/memory/__init__.py`
- Create: `src/assistant/memory/store.py`
- Modify: `tests/test_db.py`（版本号断言更新）
- Test: `tests/test_memory_store.py`

**Interfaces:**
- Consumes: `Database`
- Produces:
  - `Memory` dataclass：`id: int`、`type: str`、`content: str`、`tags: str | None`、`importance: float`、`created_at: str`、`last_accessed_at: str | None`、`access_count: int`、`source_session: str | None`
  - `MemoryStore(db: Database)`：
    - `add(type, content, tags=None, importance=0.5, source_session=None) -> int`
    - `get(memory_id) -> Memory | None`、`list_all() -> list[Memory]`
    - `delete(memory_id)`、`clear()`、`export() -> list[dict]`
    - `touch(memory_id)` —— last_accessed_at=now、access_count+1
    - 每次 add/delete/clear 同步维护 `memories_fts`（FTS5 trigram）虚拟表

- [ ] **Step 1: 写失败测试**

`tests/test_memory_store.py`:
```python
from assistant.memory.store import MemoryStore
from assistant.storage.db import Database


def make_store():
    db = Database(":memory:")
    db.migrate()
    return db, MemoryStore(db)


def test_add_and_get():
    db, store = make_store()
    mid = store.add("fact", "我在杭州工作", importance=0.8)
    m = store.get(mid)
    assert m.type == "fact"
    assert m.content == "我在杭州工作"
    assert m.importance == 0.8


def test_fts_index_syncs_on_add_and_delete():
    db, store = make_store()
    mid = store.add("fact", "喜欢喝咖啡")
    row = db.query_one(
        "SELECT content FROM memories_fts WHERE content MATCH ?", ("咖啡",))
    assert row is not None
    store.delete(mid)
    assert db.query_one(
        "SELECT content FROM memories_fts WHERE content MATCH ?",
        ("咖啡",)) is None


def test_touch_updates_access():
    db, store = make_store()
    mid = store.add("fact", "测试", importance=0.5)
    store.touch(mid)
    m = store.get(mid)
    assert m.access_count == 1
    assert m.last_accessed_at is not None


def test_list_clear_export():
    db, store = make_store()
    store.add("fact", "A")
    store.add("preference", "B")
    assert len(store.list_all()) == 2
    exported = store.export()
    assert exported[0]["content"] == "A"
    store.clear()
    assert store.list_all() == []
    assert db.query("SELECT COUNT(*) AS n FROM memories_fts")[0]["n"] == 0
```

- [ ] **Step 2: 修改 db.py 追加迁移 v2 并更新旧测试**

`src/assistant/storage/db.py` 的 `MIGRATIONS` 列表追加第二个元素:
```python
    # v2: 记忆全文索引（trigram 分词，中文友好）
    """
    CREATE VIRTUAL TABLE memories_fts USING fts5(
        content, tokenize='trigram'
    );
    """,
```

`tests/test_db.py` 的 `test_migrate_creates_tables` 更新为:
```python
def test_migrate_creates_tables():
    db = Database(":memory:")
    db.migrate()
    tables = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sessions", "messages", "task_steps", "memories",
            "settings", "schema_version"} <= tables
    assert "memories_fts" in tables
    assert db.schema_version() == 2


def test_migrate_is_idempotent():
    db = Database(":memory:")
    db.migrate()
    db.migrate()
    assert db.schema_version() == 2
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_memory_store.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现**

`src/assistant/memory/store.py`:
```python
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
```

`src/assistant/memory/__init__.py`（空文件）。

- [ ] **Step 5: 跑测试确认通过（含回归）**

Run: `.venv/bin/python -m pytest tests/test_memory_store.py tests/test_db.py -v`
Expected: 4 PASS + 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/assistant/memory src/assistant/storage/db.py tests/test_memory_store.py tests/test_db.py
git commit -m "feat: memory store with fts5 trigram index"
```

---

### Task 2: MemoryRetriever（检索注入）

**Files:**
- Create: `src/assistant/memory/retrieve.py`
- Test: `tests/test_memory_retrieve.py`

**Interfaces:**
- Consumes: `MemoryStore`
- Produces: `MemoryRetriever(store: MemoryStore)`：`retrieve(query: str, k: int = 8) -> list[Memory]`
  - 评分：FTS 命中 +1.0；`importance` 加权 0~1；`min(access_count, 10) * 0.05`；时间衰减 `exp(-天数/30)`
  - 排序取 top-k，并对每条调用 `store.touch()`
  - FTS 无命中时回退为全量按衰减+重要度排序

- [ ] **Step 1: 写失败测试**

`tests/test_memory_retrieve.py`:
```python
from assistant.memory.retrieve import MemoryRetriever
from assistant.memory.store import MemoryStore
from assistant.storage.db import Database


def make():
    db = Database(":memory:")
    db.migrate()
    store = MemoryStore(db)
    return store, MemoryRetriever(store)


def test_matching_memory_ranks_first():
    store, retriever = make()
    store.add("fact", "用户养了一只猫")
    store.add("fact", "用户喜欢爬山")
    results = retriever.retrieve("我的猫")
    assert results and results[0].content == "用户养了一只猫"


def test_no_match_falls_back_to_recency():
    store, retriever = make()
    a = store.add("fact", "AAA")
    b = store.add("fact", "BBB")
    results = retriever.retrieve("完全不相关的内容")
    assert {m.id for m in results} == {a, b}


def test_importance_boosts_ranking():
    store, retriever = make()
    low = store.add("fact", "无关但重要的事", importance=0.9)
    store.add("fact", "匹配的内容", importance=0.1)
    # 关键词命中仍应排第一
    results = retriever.retrieve("匹配")
    assert results[0].content == "匹配的内容"


def test_access_count_boosts():
    store, retriever = make()
    m1 = store.add("fact", "常用的记忆A")
    m2 = store.add("fact", "不常用的记忆B")
    for _ in range(5):
        store.touch(m2)
    results = retriever.retrieve("不相关")
    # B 访问次数多，无命中时排前
    assert results[0].id == m2


def test_retrieve_touches_results():
    store, retriever = make()
    mid = store.add("fact", "会被触达")
    retriever.retrieve("触达")
    assert store.get(mid).access_count == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_memory_retrieve.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/memory/retrieve.py`:
```python
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
        if query.strip():
            rows = self.store.db.query(
                "SELECT rowid FROM memories_fts WHERE content MATCH ? "
                "LIMIT 50", (query.strip(),))
            matched_ids = {r["rowid"] for r in rows}

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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_memory_retrieve.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/memory/retrieve.py tests/test_memory_retrieve.py
git commit -m "feat: memory retriever with fts, importance and decay ranking"
```

---

### Task 3: MemoryExtractor + MemoryResolver（沉淀与消解）

**Files:**
- Create: `src/assistant/memory/extract.py`
- Create: `src/assistant/memory/resolve.py`
- Test: `tests/test_memory_extract.py`、`tests/test_memory_resolve.py`

**Interfaces:**
- Consumes: `Provider`、`MemoryStore`
- Produces:
  - `MemoryCandidate(type: str, content: str, importance: float)`
  - `MemoryExtractor(provider, model)`：`extract(conversation: list[ChatMessage]) -> list[MemoryCandidate]` —— 提示模型输出 JSON 数组；解析失败返回 `[]`
  - `MemoryResolver(store)`：`apply(candidates, source_session=None) -> list[int]` —— 对每个候选：与现有记忆做**字符 bigram Jaccard 相似度**比较，>0.35 视为同一主题 → 更新旧记忆内容（冲突消解，返回旧 id）；否则新增（返回新 id）

- [ ] **Step 1: 写失败测试**

`tests/test_memory_extract.py`:
```python
from assistant.memory.extract import MemoryExtractor
from assistant.providers.base import ChatMessage, Completion


class FakeProvider:
    def __init__(self, answer):
        self.answer = answer

    def chat(self, messages, model, tools=None, on_delta=None):
        return Completion(content=self.answer)


JSON_OK = '```json\n[{"type": "fact", "content": "用户住在杭州", "importance": 0.8},\n{"type": "preference", "content": "喜欢简洁的回答", "importance": 0.6}]\n```'


def test_extract_parses_json():
    ex = MemoryExtractor(FakeProvider(JSON_OK), lambda: "m")
    result = ex.extract([ChatMessage("user", "我住在杭州，喜欢简洁的回答")])
    assert len(result) == 2
    assert result[0].type == "fact"
    assert result[0].content == "用户住在杭州"
    assert result[0].importance == 0.8


def test_extract_empty_array():
    ex = MemoryExtractor(FakeProvider("[]"), lambda: "m")
    assert ex.extract([ChatMessage("user", "你好")]) == []


def test_extract_garbage_returns_empty():
    ex = MemoryExtractor(FakeProvider("这不是 JSON"), lambda: "m")
    assert ex.extract([ChatMessage("user", "hi")]) == []


def test_extract_provider_error_returns_empty():
    class Boom:
        def chat(self, *a, **kw):
            raise RuntimeError("down")

    ex = MemoryExtractor(Boom(), lambda: "m")
    assert ex.extract([ChatMessage("user", "hi")]) == []
```

`tests/test_memory_resolve.py`:
```python
from assistant.memory.extract import MemoryCandidate
from assistant.memory.resolve import MemoryResolver
from assistant.memory.store import MemoryStore
from assistant.storage.db import Database


def make():
    db = Database(":memory:")
    db.migrate()
    return MemoryStore(db), MemoryResolver(MemoryStore(db))


def test_new_candidates_are_added():
    store, resolver = make()
    ids = resolver.apply([MemoryCandidate("fact", "用户住在北京", 0.7)])
    assert len(ids) == 1
    assert store.get(ids[0]).content == "用户住在北京"


def test_similar_content_updates_instead_of_duplicating():
    store, resolver = make()
    old_id = store.add("fact", "用户住在北京")
    ids = resolver.apply(
        [MemoryCandidate("fact", "用户住在杭州", 0.7)])
    assert ids == [old_id]                # 更新旧记忆而非新增
    assert store.get(old_id).content == "用户住在杭州"
    assert len(store.list_all()) == 1     # 没有重复


def test_unrelated_content_adds_new():
    store, resolver = make()
    old_id = store.add("fact", "用户住在北京")
    ids = resolver.apply(
        [MemoryCandidate("fact", "用户喜欢打篮球", 0.5)])
    assert ids != [old_id]
    assert len(store.list_all()) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_memory_extract.py tests/test_memory_resolve.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/memory/extract.py`:
```python
import json
from dataclasses import dataclass

from assistant.providers.base import ChatMessage, Provider


@dataclass
class MemoryCandidate:
    type: str
    content: str
    importance: float


_EXTRACT_SYSTEM = (
    "从对话中提炼关于用户的长期记忆。只输出 JSON 数组，每个元素：\n"
    '{"type": "fact|preference|event", "content": "一句话记忆（第三人称，如：用户住在杭州）",'
    ' "importance": 0.0~1.0}\n'
    "没有值得记住的内容时输出 []。不要输出任何其他文字。"
)


class MemoryExtractor:
    def __init__(self, provider: Provider, model):
        self.provider = provider
        self.model = model

    def extract(self, conversation: list[ChatMessage]) -> list[MemoryCandidate]:
        try:
            result = self.provider.chat(
                [ChatMessage("system", _EXTRACT_SYSTEM),
                 ChatMessage("user", self._format(conversation))],
                model=self.model())
            return self._parse(result.content)
        except Exception:
            return []

    def _format(self, conversation) -> str:
        lines = [f"{m.role}: {m.content}" for m in conversation[-10:]]
        return "\n".join(lines)

    def _parse(self, text: str) -> list[MemoryCandidate]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            data = json.loads(cleaned)
            return [MemoryCandidate(
                type=str(item.get("type", "fact")),
                content=str(item["content"]),
                importance=float(item.get("importance", 0.5)))
                for item in data if isinstance(item, dict) and item.get("content")]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return []
```

`src/assistant/memory/resolve.py`:
```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_memory_extract.py tests/test_memory_resolve.py -v`
Expected: 4 PASS + 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/memory tests/test_memory_extract.py tests/test_memory_resolve.py
git commit -m "feat: memory extraction and conflict resolution"
```

---

### Task 4: PersonaManager（人设管理）

**Files:**
- Create: `src/assistant/memory/persona.py`
- Test: `tests/test_persona.py`

**Interfaces:**
- Consumes: `Database`、`core.chat.DEFAULT_PERSONA`
- Produces:
  - `PRESET_PERSONAS: dict[str, str]` —— 3 个预置人设（"默认助理"=DEFAULT_PERSONA、"温柔陪伴"、"高效干练"）
  - `PersonaManager(db: Database)`：
    - `active() -> str` —— 自定义优先，否则当前预置，否则 DEFAULT_PERSONA
    - `set_preset(name: str)`、`set_custom(text: str)`（空串=清除自定义）
    - `list_presets() -> list[str]`、`current_preset() -> str`
    - 存储于 settings 表：`persona_preset`、`persona_custom`

- [ ] **Step 1: 写失败测试**

`tests/test_persona.py`:
```python
from assistant.core.chat import DEFAULT_PERSONA
from assistant.memory.persona import PRESET_PERSONAS, PersonaManager
from assistant.storage.db import Database


def make():
    db = Database(":memory:")
    db.migrate()
    return PersonaManager(db)


def test_default_active_is_default_persona():
    pm = make()
    assert pm.active() == DEFAULT_PERSONA


def test_set_preset():
    pm = make()
    pm.set_preset("温柔陪伴")
    assert pm.active() == PRESET_PERSONAS["温柔陪伴"]
    assert pm.current_preset() == "温柔陪伴"


def test_custom_overrides_preset():
    pm = make()
    pm.set_preset("高效干练")
    pm.set_custom("你是一只猫。")
    assert pm.active() == "你是一只猫。"


def test_clear_custom_restores_preset():
    pm = make()
    pm.set_preset("高效干练")
    pm.set_custom("你是一只猫。")
    pm.set_custom("")
    assert pm.active() == PRESET_PERSONAS["高效干练"]


def test_persists_across_instances():
    db = Database(":memory:")
    db.migrate()
    PersonaManager(db).set_preset("温柔陪伴")
    assert PersonaManager(db).active() == PRESET_PERSONAS["温柔陪伴"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_persona.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/memory/persona.py`:
```python
from assistant.core.chat import DEFAULT_PERSONA
from assistant.storage.db import Database

PRESET_PERSONAS: dict[str, str] = {
    "默认助理": DEFAULT_PERSONA,
    "温柔陪伴": (
        "你是 assistant，用户最贴心的陪伴。语气温柔、有耐心，"
        "善于倾听和共情。回答用中文，像老朋友聊天。"
        "能帮用户干活，但重点是让人感到被理解和陪伴。"
    ),
    "高效干练": (
        "你是 assistant，一位高效的执行助理。回答简短、直接、"
        "条理清晰，用最少的话把事情说清楚。优先给结论，再给细节。"
        "干活时汇报进度与结果，不废话。"
    ),
}


class PersonaManager:
    KEY_PRESET = "persona_preset"
    KEY_CUSTOM = "persona_custom"

    def __init__(self, db: Database):
        self.db = db

    def _get(self, key: str) -> str | None:
        row = self.db.query_one(
            "SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else None

    def _set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value))

    def list_presets(self) -> list[str]:
        return list(PRESET_PERSONAS)

    def current_preset(self) -> str:
        return self._get(self.KEY_PRESET) or "默认助理"

    def set_preset(self, name: str) -> None:
        if name not in PRESET_PERSONAS:
            raise ValueError(f"未知人设: {name}")
        self._set(self.KEY_PRESET, name)

    def set_custom(self, text: str) -> None:
        if text.strip():
            self._set(self.KEY_CUSTOM, text.strip())
        else:
            self.db.execute("DELETE FROM settings WHERE key=?",
                            (self.KEY_CUSTOM,))

    def active(self) -> str:
        custom = self._get(self.KEY_CUSTOM)
        if custom:
            return custom
        return PRESET_PERSONAS.get(self.current_preset(), DEFAULT_PERSONA)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_persona.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/memory/persona.py tests/test_persona.py
git commit -m "feat: persona manager with presets and custom prompt"
```

---

### Task 5: ChatService 记忆注入与沉淀

**Files:**
- Modify: `src/assistant/core/chat.py`
- Test: `tests/test_chat_memory.py`

**Interfaces:**
- Consumes: `MemoryRetriever`、`MemoryExtractor`、`MemoryResolver`
- Produces: `ChatService` 扩展（可选参数向后兼容，Plan 1 测试不受影响）：
  - 构造新增 `retriever=None, extractor=None, resolver=None`
  - `stream_reply`：system prompt = 人设 + 检索到的记忆（top 8 条，格式见实现）；回复落库后同步执行提取+消解（任一环节异常静默吞掉，不影响聊天）

- [ ] **Step 1: 写失败测试**

`tests/test_chat_memory.py`:
```python
from assistant.core.chat import ChatService
from assistant.core.sessions import SessionManager
from assistant.memory.extract import MemoryExtractor
from assistant.memory.resolve import MemoryResolver
from assistant.memory.retrieve import MemoryRetriever
from assistant.memory.store import MemoryStore
from assistant.providers.base import Completion
from assistant.storage.db import Database


class ScriptedProvider:
    """第一次调用=聊天回复，第二次=记忆提取 JSON。"""

    def __init__(self, reply, extract):
        self.reply = reply
        self.extract = extract
        self.calls = 0
        self.first_prompt = None

    def chat(self, messages, model, tools=None, on_delta=None):
        self.calls += 1
        if self.calls == 1:
            self.first_prompt = messages[0].content
            if on_delta:
                for ch in self.reply:
                    on_delta(ch)
            return Completion(content=self.reply)
        return Completion(content=self.extract)


def make():
    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    store = MemoryStore(db)
    store.add("fact", "用户养了一只猫叫团团", importance=0.9)
    provider = ScriptedProvider(
        reply="团团很可爱！",
        extract='[{"type": "preference", "content": "用户喜欢猫", "importance": 0.7}]')
    service = ChatService(
        sessions, provider, model=lambda: "m",
        retriever=MemoryRetriever(store),
        extractor=MemoryExtractor(provider, lambda: "m"),
        resolver=MemoryResolver(store))
    return sessions, store, provider, service


def test_system_prompt_injects_relevant_memory():
    sessions, store, provider, service = make()
    sid = sessions.create()
    service.stream_reply(sid, "我的猫叫什么", on_delta=lambda t: None)
    assert "团团" in provider.first_prompt
    assert "长期记忆" in provider.first_prompt


def test_reply_triggers_extraction_and_resolve():
    sessions, store, provider, service = make()
    sid = sessions.create()
    service.stream_reply(sid, "我很喜欢猫", on_delta=lambda t: None)
    memories = {m.content for m in store.list_all()}
    assert "用户喜欢猫" in memories
    assert len(store.list_all()) == 2  # 原有 1 条 + 新增 1 条（主题不同不覆盖）


def test_extraction_error_does_not_break_chat():
    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    store = MemoryStore(db)

    class ChatOkExtractBoom:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, model, tools=None, on_delta=None):
            self.calls += 1
            if self.calls == 1:
                if on_delta:
                    on_delta("好")
                return Completion(content="好")
            raise RuntimeError("extract down")

    provider = ChatOkExtractBoom()
    service = ChatService(
        sessions, provider, model=lambda: "m",
        retriever=MemoryRetriever(store),
        extractor=MemoryExtractor(provider, lambda: "m"),
        resolver=MemoryResolver(store))
    sid = sessions.create()
    reply = service.stream_reply(sid, "hi", on_delta=lambda t: None)
    assert reply == "好"   # 提取失败不影响聊天
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_chat_memory.py -v`
Expected: FAIL（构造参数不存在）

- [ ] **Step 3: 实现（修改 core/chat.py）**

`src/assistant/core/chat.py` 完整内容:
```python
from typing import Callable, Protocol

from assistant.core.sessions import SessionManager
from assistant.providers.base import ChatMessage, Provider


class SystemPromptFactory(Protocol):
    def __call__(self) -> str: ...


DEFAULT_PERSONA = (
    "你是 assistant，用户电脑上的私人 AI 助手。性格温和、可靠、偶尔幽默。"
    "回答用中文，简洁自然，像朋友一样。"
    "你有能力操作电脑（文件、应用、命令、浏览器），但只在用户要求时动手。"
)

MEMORY_SECTION = "\n\n关于用户的长期记忆（仅供参考，不要主动提起）：\n{memories}"


class ChatService:
    history_limit = 20

    def __init__(
        self,
        sessions: SessionManager,
        provider: Provider,
        model: Callable[[], str],
        system_prompt: SystemPromptFactory | None = None,
        retriever=None,      # MemoryRetriever | None
        extractor=None,      # MemoryExtractor | None
        resolver=None,       # MemoryResolver | None
    ):
        self.sessions = sessions
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt or (lambda: DEFAULT_PERSONA)
        self.retriever = retriever
        self.extractor = extractor
        self.resolver = resolver

    def _build_system(self, user_text: str) -> str:
        base = self.system_prompt()
        if not self.retriever:
            return base
        memories = self.retriever.retrieve(user_text, k=8)
        if not memories:
            return base
        lines = "\n".join(f"- {m.content}" for m in memories)
        return base + MEMORY_SECTION.format(memories=lines)

    def stream_reply(
        self,
        session_id: str,
        user_text: str,
        on_delta: Callable[[str], None],
    ) -> str:
        self.sessions.add_message(session_id, "user", user_text)
        history = self.sessions.history(session_id)
        messages = [ChatMessage("system", self._build_system(user_text))]
        messages += history[-self.history_limit:]
        completion = self.provider.chat(
            messages, model=self.model(), on_delta=on_delta)
        reply = completion.content
        if reply:
            self.sessions.add_message(session_id, "assistant", reply)
            self._update_memories(session_id, user_text, reply)
        return reply

    def _update_memories(self, session_id, user_text, reply) -> None:
        if not (self.extractor and self.resolver):
            return
        try:
            candidates = self.extractor.extract([
                ChatMessage("user", user_text),
                ChatMessage("assistant", reply),
            ])
            if candidates:
                self.resolver.apply(candidates, source_session=session_id)
        except Exception:
            pass  # 记忆沉淀失败不影响聊天
```

- [ ] **Step 4: 跑测试确认通过（含回归）**

Run: `.venv/bin/python -m pytest tests/test_chat_memory.py tests/test_chat.py -v`
Expected: 4 PASS + Plan 1 的 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/core/chat.py tests/test_chat_memory.py
git commit -m "feat: memory injection and extraction in chat service"
```

---

### Task 6: 记忆管理 UI + 人设选择 UI

**Files:**
- Modify: `src/assistant/ui/settings_dialog.py`
- Modify: `src/assistant/main.py`（装配 PersonaManager/MemoryStore/Retriever 进 ChatService）

**Interfaces:**
- Consumes: `MemoryStore`、`PersonaManager`
- Produces:
  - `SettingsDialog` 改为 QTabWidget：页签"模型"（原表单）、"人设"（预置下拉 + 自定义文本框）、"记忆"（列表 + 删除选中/导出/清空按钮）
  - 构造签名：`SettingsDialog(cfg, secrets, persona: PersonaManager | None, store: MemoryStore | None, parent=None)`

- [ ] **Step 1: 实现 UI 修改**

`src/assistant/ui/settings_dialog.py` 完整替换:
```python
import json

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from assistant.storage.config import AppConfig
from assistant.storage.secrets import SecretsStore


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, secrets: SecretsStore,
                 persona=None, store=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self._secrets = secrets
        self._cfg = cfg
        self._persona = persona
        self._store = store
        self.resize(560, 420)

        tabs = QTabWidget()
        tabs.addTab(self._model_tab(), "模型")
        tabs.addTab(self._persona_tab(), "人设")
        tabs.addTab(self._memory_tab(), "记忆")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _model_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        if self._secrets:
            existing = self._secrets.get(self._cfg.models.provider)
            if existing:
                self.api_key.setPlaceholderText("已保存（留空保持不变）")
        self.base_url = QLineEdit(self._cfg.models.base_url)
        self.model = QLineEdit(self._cfg.models.model)
        self.task_model = QLineEdit(self._cfg.models.task_model)
        self.autopilot = QCheckBox("默认开启自动驾驶")
        self.autopilot.setChecked(self._cfg.autopilot_default)
        form.addRow("API Key", self.api_key)
        form.addRow("Base URL", self.base_url)
        form.addRow("聊天模型", self.model)
        form.addRow("任务模型", self.task_model)
        form.addRow("", self.autopilot)
        return w

    def _persona_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("预置人设："))
        self.persona_combo = QComboBox()
        if self._persona:
            self.persona_combo.addItems(self._persona.list_presets())
            self.persona_combo.setCurrentText(self._persona.current_preset())
        row.addWidget(self.persona_combo, 1)
        layout.addLayout(row)
        layout.addWidget(QLabel("自定义 system prompt（留空使用预置）："))
        self.custom_prompt = QPlainTextEdit()
        if self._persona:
            custom = self._persona._get(self._persona.KEY_CUSTOM)
            if custom:
                self.custom_prompt.setPlainText(custom)
        layout.addWidget(self.custom_prompt)
        return w

    def _memory_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        self.memory_list = QListWidget()
        if self._store:
            for m in self._store.list_all():
                self.memory_list.addItem(f"[{m.type}] {m.content}")
        layout.addWidget(self.memory_list)
        row = QHBoxLayout()
        delete_btn = QPushButton("删除选中")
        delete_btn.clicked.connect(self._delete_selected)
        export_btn = QPushButton("导出 JSON")
        export_btn.clicked.connect(self._export)
        clear_btn = QPushButton("清空全部")
        clear_btn.clicked.connect(self._clear_all)
        row.addWidget(delete_btn)
        row.addWidget(export_btn)
        row.addWidget(clear_btn)
        layout.addLayout(row)
        return w

    def _reload_memories(self):
        self.memory_list.clear()
        if self._store:
            for m in self._store.list_all():
                self.memory_list.addItem(f"[{m.type}] {m.content}")

    def _delete_selected(self):
        if not self._store:
            return
        memories = self._store.list_all()
        row = self.memory_list.currentRow()
        if 0 <= row < len(memories):
            self._store.delete(memories[row].id)
            self._reload_memories()

    def _export(self):
        if not self._store:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出记忆", "memories.json")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._store.export(), f, ensure_ascii=False, indent=2)

    def _clear_all(self):
        if not self._store:
            return
        if QMessageBox.question(self, "确认", "清空全部记忆？此操作不可撤销。") \
                == QMessageBox.Yes:
            self._store.clear()
            self._reload_memories()

    def result_config(self) -> AppConfig:
        self._cfg.models.base_url = self.base_url.text().strip()
        self._cfg.models.model = self.model.text().strip() or "deepseek-chat"
        self._cfg.models.task_model = self.task_model.text().strip() or "deepseek-chat"
        self._cfg.autopilot_default = self.autopilot.isChecked()
        return self._cfg

    def result_api_key(self) -> str:
        return self.api_key.text().strip()

    def result_persona(self):
        if not self._persona:
            return
        self._persona.set_preset(self.persona_combo.currentText())
        self._persona.set_custom(self.custom_prompt.toPlainText().strip())

    def accept(self):
        key = self.result_api_key()
        if key and self._secrets:
            self._secrets.set(self._cfg.models.provider, key)
        self.result_persona()
        super().accept()
```

- [ ] **Step 2: 修改 main.py 装配**

`main()` 中 sessions 之后插入:
```python
    persona = PersonaManager(db)
    memory_store = MemoryStore(db)
    retriever = MemoryRetriever(memory_store)
    extractor = MemoryExtractor(provider, model=lambda: cfg.models.model)
    resolver = MemoryResolver(memory_store)

    chat = ChatService(sessions, provider, model=lambda: cfg.models.model,
                       system_prompt=persona.active,
                       retriever=retriever, extractor=extractor,
                       resolver=resolver)
```
`_open_settings` 调用处同步更新（`SettingsDialog(self.cfg, self.secrets, persona, memory_store, self)`），MainWindow 需要 persona 与 memory_store —— 构造函数再追加两个可选参数 `persona=None, memory_store=None` 并保存。

对应新增 import：`from assistant.memory.extract import MemoryExtractor`、`from assistant.memory.persona import PersonaManager`、`from assistant.memory.resolve import MemoryResolver`、`from assistant.memory.retrieve import MemoryRetriever`、`from assistant.memory.store import MemoryStore`。

- [ ] **Step 3: 回归测试**

Run: `.venv/bin/python -m pytest tests/test_ui_smoke.py -v`
Expected: 3 PASS（MainWindow 新增可选参数有默认值，旧测试无需改）

- [ ] **Step 4: 手工验证**

Run: `.venv/bin/python -m assistant`
Expected：
1. 聊天（"我叫小明，住在杭州，喜欢简洁"）→ 回复正常
2. 再次发"你还记得我住哪吗"→ 回复能用到"杭州"（记忆已注入）
3. 设置 → 记忆页签：能看到沉淀的记忆；删除/导出/清空生效
4. 设置 → 人设页签：切"高效干练"后聊天口吻明显变化；自定义 prompt 生效
5. 说"我搬到上海了" → 记忆页签中"住在杭州"被更新为"住在上海"（消解生效），无重复条目

- [ ] **Step 5: Commit**

```bash
git add src/assistant/ui/settings_dialog.py src/assistant/main.py
git commit -m "feat: memory and persona management ui"
```

---

### Task 7: 托盘 + 全局热键 + 开机自启

**Files:**
- Create: `src/assistant/ui/tray.py`
- Create: `src/assistant/ui/hotkey.py`
- Create: `src/assistant/core/platform.py`
- Modify: `src/assistant/ui/main_window.py`（关闭隐藏到托盘）
- Modify: `src/assistant/main.py`（装配托盘/热键/自启）
- Test: `tests/test_platform.py`

**Interfaces:**
- Consumes: `Policy`、`AppConfig`、`ConfigManager`
- Produces:
  - `core/platform.set_autostart(enable: bool) -> bool` —— winreg HKCU Run 键；非 Windows 返回 False
  - `TrayIcon(icon, window, policy, cfg, on_quit)`（QSystemTrayIcon 子类）—— 菜单：显示主窗口 / 自动驾驶（勾选切换 → policy.set_autopilot）/ 退出
  - `HotkeyManager(hotkey: str, on_activate: Callable)` —— pynput GlobalHotKeys 后台线程；`start()`/`stop()`；监听器启动失败静默禁用

- [ ] **Step 1: 写失败测试（仅平台函数）**

`tests/test_platform.py`:
```python
import sys

import pytest

from assistant.core.platform import set_autostart


@pytest.mark.skipif(sys.platform == "win32",
                    reason="win32 需要真实注册表，手工验证")
def test_autostart_noop_on_non_windows():
    assert set_autostart(True) is False
    assert set_autostart(False) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_platform.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/core/platform.py`:
```python
import sys


def set_autostart(enable: bool) -> bool:
    """开机自启（HKCU Run）。非 Windows 环境返回 False。"""
    if sys.platform != "win32":
        return False
    import winreg
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0,
                             winreg.KEY_SET_VALUE)
    except OSError:
        return False
    try:
        if enable:
            exe = f'"{sys.executable}"'
            winreg.SetValueEx(key, "assistant", 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(key, "assistant")
            except FileNotFoundError:
                pass
        return True
    finally:
        winreg.CloseKey(key)
```

`src/assistant/ui/hotkey.py`:
```python
import threading
from typing import Callable


class HotkeyManager:
    """pynput 全局热键。监听器启动失败（无桌面环境）静默禁用。"""

    def __init__(self, hotkey: str, on_activate: Callable[[], None]):
        self.hotkey = hotkey
        self.on_activate = on_activate
        self._listener = None
        self._thread = None

    def start(self) -> bool:
        if not self.hotkey or self._listener:
            return False
        try:
            from pynput import keyboard
            self._listener = keyboard.GlobalHotKeys(
                {self.hotkey: self.on_activate})
            self._thread = threading.Thread(
                target=self._listener.run, daemon=True)
            self._thread.start()
            return True
        except Exception:
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
```

`src/assistant/ui/tray.py`:
```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from assistant.agent.safety import Policy
from assistant.storage.config import AppConfig


def _icon() -> QIcon:
    from PySide6.QtGui import QPixmap
    pm = QPixmap(64, 64)
    pm.fill(Qt.darkCyan)
    return QIcon(pm)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, policy: Policy, cfg: AppConfig, on_quit):
        super().__init__(_icon(), window)
        self.window = window
        self.policy = policy
        self.cfg = cfg
        self.on_quit = on_quit

        menu = QMenu()
        show_action = QAction("显示主窗口", menu)
        show_action.triggered.connect(self._show)
        self.autopilot_action = QAction("自动驾驶", menu)
        self.autopilot_action.setCheckable(True)
        self.autopilot_action.setChecked(cfg.autopilot_default)
        self.autopilot_action.toggled.connect(self._toggle_autopilot)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(on_quit)
        menu.addAction(show_action)
        menu.addAction(self.autopilot_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.setContextMenu(menu)
        self.activated.connect(self._activated)

    def _show(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _toggle_autopilot(self, on: bool):
        self.policy.set_autopilot(on)
        self.cfg.autopilot_default = on
        self.showMessage("assistant", "自动驾驶已开启" if on else "自动驾驶已关闭")

    def _activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._show()
```

- [ ] **Step 4: MainWindow 关闭行为**

`main_window.py` 追加:
```python
    def closeEvent(self, event):
        # 关闭 = 隐藏到托盘（由 main.py 注入 tray）
        if getattr(self, "tray", None) and self.tray.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()
```

- [ ] **Step 5: main.py 装配托盘/热键**

```python
    window = MainWindow(sessions, chat, cfg, secrets, router,
                        persona=persona, memory_store=memory_store)

    tray = TrayIcon(window, policy, cfg, on_quit=lambda: (
        tray.hide(), app.quit()))
    window.tray = tray
    tray.show()

    app.setQuitOnLastWindowClosed(False)
    if cfg.autostart:
        set_autostart(True)   # 应用内幂等刷新

    hotkey = HotkeyManager(cfg.hotkey, on_activate=lambda: (
        window.show() if window.isHidden() else window.hide()))
    hotkey.start()
```
（`_open_settings` 中勾选开机自启后调用 `set_autostart`：SettingsDialog 增加 `autostart` 复选框，`result_config` 读取，`accept()` 中若值变化则调用 `set_autostart`。为最小化改动：在 `_model_tab` 加 `self.autostart_check = QCheckBox("开机自启")`、`setChecked(cfg.autostart)`；`result_config` 同步；MainWindow `_open_settings` 里 accept 后 `set_autostart(cfg.autostart)`。）

- [ ] **Step 6: 跑测试**

Run: `.venv/bin/python -m pytest tests/test_platform.py tests/test_ui_smoke.py -v`
Expected: 1 PASS + 3 PASS

- [ ] **Step 7: 手工验证（开发机可验托盘/热键；自启留 Windows）**

Run: `.venv/bin/python -m assistant`
Expected：
1. 托盘出现图标；点关闭按钮窗口隐藏而不是退出；托盘菜单能重新打开
2. 全局热键 Ctrl+Alt+Space 唤起/隐藏窗口
3. 托盘勾选"自动驾驶"后，删除文件任务不再弹确认
4. （Windows 上）设置勾选开机自启 → 重启系统后自动启动

- [ ] **Step 8: Commit**

```bash
git add src/assistant/ui/tray.py src/assistant/ui/hotkey.py src/assistant/core/platform.py src/assistant/ui/main_window.py src/assistant/ui/settings_dialog.py src/assistant/main.py tests/test_platform.py
git commit -m "feat: system tray, global hotkey and autostart"
```

---

### Task 8: 打包 exe + README

**Files:**
- Modify: `pyproject.toml`（dev extra 加 `pyinstaller>=6.0`）
- Create: `assistant.spec`
- Create: `build.py`
- Modify: `src/assistant/tools/browser.py`（chromium 缺失时自动下载）
- Create: `README.md`
- Test: `tests/test_browser.py` 追加（chromium 自动下载触发逻辑，monkeypatch）

**Interfaces:**
- Consumes: 全部模块
- Produces:
  - `build.py` —— 本地一键构建：`python build.py` → `dist/assistant.exe`（Windows）或 `dist/assistant`（Linux 调试）
  - `BrowserTool._ensure_browser` 增强：launch 抛出 "Executable doesn't exist" 类错误时，用 `sys.executable -m playwright install chromium` 自动下载一次后重试

- [ ] **Step 1: 写 spec 与脚本**

`assistant.spec`:
```python
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
for pkg in ("markdown", "pygments", "trafilatura"):
    hiddenimports += collect_submodules(pkg)

a = Analysis(
    ["src/assistant/main.py"],
    pathex=["src"],
    hiddenimports=hiddenimports + collect_submodules("playwright"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="assistant",
    console=False,
    upx=False,
)
```

`build.py`:
```python
"""本地构建脚本：python build.py"""
import subprocess
import sys


def main():
    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", "--clean",
         "--noconfirm", "assistant.spec"])
    print("构建完成：dist/assistant(.exe)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 写失败测试**

`tests/test_browser.py` 追加:
```python
def test_launch_failure_triggers_chromium_install(monkeypatch):
    import subprocess as sp

    class FakePlaywright:
        class _PW:
            class chromium:
                @staticmethod
                def launch(headless=True):
                    raise Exception(
                        "Executable doesn't exist at ...playwright...")

        @staticmethod
        def start():
            return FakePlaywright._PW()

    calls = []

    def fake_install(cmd, **kw):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 0)

    monkeypatch.setattr("sys.executable", "/fake/python")
    monkeypatch.setattr(sp, "run", fake_install)
    from assistant.tools.browser import BrowserTool
    tool = BrowserTool()
    monkeypatch.setattr("playwright.sync_api.sync_playwright",
                        lambda: FakePlaywright())
    r = tool.execute("fetch_page", {"url": "http://example.com"})
    assert not r.ok                      # 安装后仍失败（Fake 不提供浏览器）
    assert calls                            # 已尝试自动下载 chromium
    assert "playwright" in " ".join(calls[0])
    assert "chromium" in " ".join(calls[0])
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_browser.py::test_launch_failure_triggers_chromium_install -v`
Expected: FAIL

- [ ] **Step 4: 修改 browser.py**

`_ensure_browser` 替换为:
```python
    _install_attempted = False

    def _ensure_browser(self):
        if self._browser is None:
            self._pw = sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch(headless=True)
            except Exception as exc:
                if "Executable doesn't exist" in str(exc) \
                        and not self._install_attempted:
                    self._install_attempted = True
                    import subprocess
                    import sys
                    subprocess.run(
                        [sys.executable, "-m", "playwright", "install",
                         "chromium"], check=False)
                    self._browser = self._pw.chromium.launch(headless=True)
                else:
                    raise
```

- [ ] **Step 5: 写 README.md**

```markdown
# assistant

Windows 个人 AI 助手：聊天陪伴（人设 + 长期记忆）+ 系统级干活 agent。

## 功能
- 聊天：DeepSeek 默认，流式输出，Markdown 渲染
- 干活：文件操作、启动/关闭应用、PowerShell、浏览器搜索与抓取
- 多步任务：目标 → 自动拆解 → 执行 → 失败自纠 → 汇报
- 长期记忆：自动沉淀、冲突消解、检索注入（本地 SQLite，可导出/清空）
- 人设：预置 3 套 + 自定义 system prompt
- 托盘常驻、全局热键（Ctrl+Alt+Space）、开机自启
- 安全：高风控操作确认 + 自动驾驶开关

## 开发
\`\`\`bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Windows: .venv\\Scripts\\
.venv/bin/playwright install chromium
.venv/bin/python -m pytest
.venv/bin/python -m assistant
\`\`\`

## 构建（Windows 10/11 64 位）
\`\`\`bash
pip install -e ".[dev, windows]"
python build.py          # 产物 dist/assistant.exe
\`\`\`

## 使用
1. 首次启动进入设置，填入 DeepSeek API Key（默认 base_url https://api.deepseek.com/v1）
2. 首次使用浏览器功能会自动下载 chromium（约 150MB）
3. 数据存于 %APPDATA%\\assistant\\（数据库、配置、密钥）
```

- [ ] **Step 6: 跑测试**

Run: `.venv/bin/python -m pytest tests/test_browser.py -v`
Expected: 4 PASS

- [ ] **Step 7: 试构建（开发机 Linux 验证流程，最终在 Windows 上构建）**

Run: `.venv/bin/pip install -e ".[dev]" && .venv/bin/python build.py`
Expected: 生成 `dist/assistant`（Linux 二进制；Windows 上同名流程产出 `assistant.exe`）

- [ ] **Step 8: Commit**

```bash
git add assistant.spec build.py README.md src/assistant/tools/browser.py tests/test_browser.py pyproject.toml
git commit -m "feat: packaging spec, build script and readme"
```

---

### Task 9: 端到端验收清单

**Files:**
- Create: `docs/acceptance-v1.md`

- [ ] **Step 1: 写验收清单**

`docs/acceptance-v1.md` 内容:

```markdown
# assistant v1 验收清单

## 聊天陪伴线
- [ ] 流式回复、Markdown 渲染、代码高亮
- [ ] 会话新建/重命名/删除/搜索；历史持久化，重启不丢
- [ ] 人设：预置 3 套可切换；自定义 prompt 生效；任务线不受人设影响
- [ ] 长期记忆：对话自动沉淀；重复主题自动消解不重复；后续对话能用到记忆
- [ ] 记忆管理：查看/删除/导出 JSON/一键清空

## 干活线
- [ ] 意图分类：聊天走聊天线，干活走任务线
- [ ] 文件：读/写/列目录/搜索/移动/复制/删除
- [ ] 应用：启动/关闭
- [ ] 命令：PowerShell 执行、超时、输出截断
- [ ] 浏览器：搜索呈现结果；抓取网页正文卡片
- [ ] 多步任务：计划 → 执行 → 失败自纠（最多 3 轮）→ 汇报
- [ ] 停止：执行中可随时中断
- [ ] C 级预留：computer 工具存在且返回"后续版本启用"

## 安全
- [ ] 高风控操作（删文件/执行命令/关进程）默认弹确认
- [ ] 自动驾驶开启后放行且聊天流明示；托盘可随时切换
- [ ] API key 非明文存储（DPAPI）

## 桌面集成
- [ ] 托盘：显示/退出/自动驾驶开关；关闭窗口隐藏不退出
- [ ] 全局热键 Ctrl+Alt+Space 唤起/隐藏
- [ ] 开机自启（Windows 实测注册表 HKCU Run）

## 发布
- [ ] dist/assistant.exe 在干净 Windows 10/11 机器可启动
- [ ] 首次浏览器使用自动下载 chromium
- [ ] 数据全部在 %APPDATA%\assistant\，删除目录即卸载
```

- [ ] **Step 2: Commit**

```bash
git add docs/acceptance-v1.md
git commit -m "docs: add v1 acceptance checklist"
```

---

## 计划完成标准

- [ ] `pytest` 全绿（累计 76 + 25 = 101 个测试）
- [ ] 验收清单逐项通过（托盘/热键/自启/打包在 Windows 上终验）
- [ ] 每条 task 已 commit
- [ ] v1.5 预留位：`reminders/`、`events/`、`tools/computer.py`、检索器 embedding 接口
