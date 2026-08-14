from assistant.core.chat import DEFAULT_PERSONA, ChatService
from assistant.core.sessions import SessionManager
from assistant.providers.base import Completion
from assistant.storage.db import Database


class FakeProvider:
    def __init__(self):
        self.calls = []
        self.kwargs = []
        self.reply = "好的，收到！"
        self.reasoning = "让我想想"

    def chat(self, messages, model, tools=None, on_delta=None,
             on_reasoning=None, on_tool_delta=None, thinking=None):
        self.calls.append(list(messages))
        self.kwargs.append({"thinking": thinking,
                            "on_reasoning": on_reasoning})
        if on_reasoning:
            for ch in self.reasoning:
                on_reasoning(ch)
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


def test_stream_reply_forwards_reasoning():
    sessions, provider, service = make_service()
    sid = sessions.create()
    reasoning = []
    reply = service.stream_reply(sid, "你好", on_delta=lambda t: None,
                                 on_reasoning=reasoning.append)
    assert "".join(reasoning) == "让我想想"
    assert reply == "好的，收到！"
    # 思考内容不入会话历史
    history = sessions.history(sid)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].content == "好的，收到！"


def test_thinking_mode_passed_to_provider():
    sessions, provider, service = make_service()
    service = ChatService(sessions, provider, model=lambda: "deepseek-chat",
                          thinking=lambda: "enabled")
    sid = sessions.create()
    service.stream_reply(sid, "hi", on_delta=lambda t: None)
    assert provider.kwargs[-1]["thinking"] == "enabled"


def test_thinking_auto_sends_none():
    sessions, provider, service = make_service()
    sid = sessions.create()
    service.stream_reply(sid, "hi", on_delta=lambda t: None)
    assert provider.kwargs[-1]["thinking"] is None


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
