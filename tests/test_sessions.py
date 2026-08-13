from assistant.core.sessions import SessionManager
from assistant.storage.db import Database


def make_manager():
    db = Database(":memory:")
    db.migrate()
    return db, SessionManager(db)


def test_create_and_list():
    db, sm = make_manager()
    sid = sm.create("第一个会话")
    sessions = sm.list()
    assert len(sessions) == 1
    assert sessions[0].id == sid
    assert sessions[0].title == "第一个会话"


def test_history_order_and_rename():
    db, sm = make_manager()
    sid = sm.create()
    sm.add_message(sid, "user", "问题")
    sm.add_message(sid, "assistant", "回答")
    history = sm.history(sid)
    assert [m.content for m in history] == ["问题", "回答"]
    sm.rename(sid, "改名")
    assert sm.list()[0].title == "改名"


def test_delete_cascades_messages():
    db, sm = make_manager()
    sid = sm.create()
    sm.add_message(sid, "user", "hi")
    sm.delete(sid)
    assert sm.list() == []
    assert db.query("SELECT COUNT(*) AS n FROM messages WHERE session_id=?",
                    (sid,))[0]["n"] == 0


def test_search_finds_by_title_and_content():
    db, sm = make_manager()
    s1 = sm.create("旅游计划")
    sm.add_message(s1, "user", "推荐杭州的景点")
    s2 = sm.create("工作")
    results = sm.search("杭州")
    assert [s.id for s in results] == [s1]
    assert sm.search("旅游")[0].id == s1
