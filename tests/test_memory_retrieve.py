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
    store.add("fact", "无关但重要的事", importance=0.9)
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
