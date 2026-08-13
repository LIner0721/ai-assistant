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
    mid = store.add("fact", "喜欢喝冰咖啡")
    # FTS5 trigram 需 ≥3 字符查询
    row = db.query_one(
        "SELECT content FROM memories_fts WHERE content MATCH ?", ("冰咖啡",))
    assert row is not None
    store.delete(mid)
    assert db.query_one(
        "SELECT content FROM memories_fts WHERE content MATCH ?",
        ("冰咖啡",)) is None


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
