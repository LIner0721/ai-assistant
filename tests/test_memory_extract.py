from assistant.memory.extract import MemoryExtractor
from assistant.providers.base import ChatMessage, Completion


class FakeProvider:
    def __init__(self, answer):
        self.answer = answer

    def chat(self, messages, model, tools=None, on_delta=None):
        return Completion(content=self.answer)


JSON_OK = ('```json\n[{"type": "fact", "content": "用户住在杭州", "importance": 0.8},\n'
           '{"type": "preference", "content": "喜欢简洁的回答", "importance": 0.6}]\n```')


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
