from assistant.agent.engine import TaskReport
from assistant.core.intent import Intent
from assistant.core.sessions import SessionManager
from assistant.core.tasks import TaskRouter
from assistant.storage.db import Database


class FakeClassifier:
    def __init__(self, intent):
        self.intent = intent

    def classify(self, text):
        return self.intent


class FakeChat:
    def __init__(self):
        self.called_with = None

    def stream_reply(self, session_id, text, on_delta,
                     on_reasoning=None):
        self.called_with = (session_id, text)
        if on_reasoning:
            on_reasoning("思考")
        on_delta("回复")
        return "回复内容"


def make_router(intent):
    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    chat = FakeChat()
    return db, sessions, TaskRouter(
        chat, FakeClassifier(intent), lambda: None, sessions)


def test_chat_route_goes_to_chat_service():
    _, sessions, router = make_router(Intent.CHAT)
    sid = sessions.create()
    result = router.route(sid, "你好", on_delta=lambda t: None,
                          on_event=lambda e: None)
    assert result == "回复内容"
    # 持久化是 ChatService 的职责（test_chat.py 已覆盖），路由器只负责委托
    assert router.chat.called_with == (sid, "你好")


def test_task_route_runs_engine_and_persists():
    _, sessions, router = make_router(Intent.TASK)

    class FakeEngine:
        def run_task(self, goal, session_id=None):
            return TaskReport(success=True, summary="搞定了", steps=[])

    router.engine_factory = lambda: FakeEngine()
    sid = sessions.create()
    events = []
    report = router.route(sid, "整理文件", on_delta=lambda t: None,
                          on_event=events.append)
    assert report.success is True
    history = sessions.history(sid)
    assert history[0].content == "整理文件"
    assert "搞定了" in history[1].content


def test_task_route_wires_on_event_into_engine():
    """引擎事件必须接上 route 传入的 on_event，否则干活过程界面看不到。"""
    _, sessions, router = make_router(Intent.TASK)
    received = {}

    class FakeEngine:
        def __init__(self):
            self.on_event = lambda e: None

        def run_task(self, goal, session_id=None):
            self.on_event({"type": "plan", "payload": {"plan": "P"}})
            return TaskReport(success=True, summary="完成", steps=[])

    engine = FakeEngine()
    router.engine_factory = lambda: engine
    seen = []
    router.route(sessions.create(), "干活", on_delta=lambda t: None,
                 on_event=seen.append)
    assert [e["type"] for e in seen] == ["plan"]
