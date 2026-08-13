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
