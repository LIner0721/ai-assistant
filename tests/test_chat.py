from assistant.core.chat import DEFAULT_PERSONA, ChatService
from assistant.core.sessions import SessionManager
from assistant.providers.base import Completion
from assistant.storage.db import Database


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.reply = "好的，收到！"

    def chat(self, messages, model, tools=None, on_delta=None):
        self.calls.append(list(messages))
        if on_delta:
            for ch in self.reply:
                on_delta(ch)
        return Completion(content=self.reply)


def make_service():
    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    provider = FakeProvider()
    service = ChatService(sessions, provider, model=lambda: "deepseek-chat")
    return sessions, provider, service


def test_stream_reply_persists_and_streams():
    sessions, provider, service = make_service()
    sid = sessions.create()
    deltas = []
    reply = service.stream_reply(sid, "你好", on_delta=deltas.append)
    assert "".join(deltas) == "好的，收到！"
    assert reply == "好的，收到！"
    history = sessions.history(sid)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[0].content == "你好"


def test_system_prompt_uses_persona():
    sessions, provider, service = make_service()
    sid = sessions.create()
    service.stream_reply(sid, "hi", on_delta=lambda t: None)
    first = provider.calls[0][0]
    assert first.role == "system"
    assert DEFAULT_PERSONA in first.content


def test_custom_system_prompt_factory():
    sessions, provider, service = make_service()
    service.system_prompt = lambda: "你是一只猫。"
    sid = sessions.create()
    service.stream_reply(sid, "hi", on_delta=lambda t: None)
    assert provider.calls[0][0].content == "你是一只猫。"
