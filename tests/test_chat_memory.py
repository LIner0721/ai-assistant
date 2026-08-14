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

    def chat(self, messages, model, tools=None, on_delta=None,
             on_reasoning=None, on_tool_delta=None, thinking=None):
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

        def chat(self, messages, model, tools=None, on_delta=None,
                 on_reasoning=None, on_tool_delta=None, thinking=None):
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
