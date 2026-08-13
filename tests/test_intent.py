from assistant.core.intent import Intent, IntentClassifier
from assistant.providers.base import Completion


class FakeProvider:
    def __init__(self, answer):
        self.answer = answer
        self.prompt = None

    def chat(self, messages, model, tools=None, on_delta=None):
        self.prompt = messages[-1].content
        return Completion(content=self.answer)


def test_classify_task():
    p = FakeProvider("TASK")
    assert IntentClassifier(p, lambda: "m").classify("帮我把文件整理一下") is Intent.TASK
    assert "帮我把文件整理一下" in p.prompt


def test_classify_chat():
    p = FakeProvider("CHAT")
    assert IntentClassifier(p, lambda: "m").classify("今天心情不好") is Intent.CHAT


def test_garbage_falls_back_to_chat():
    p = FakeProvider("随便说点什么")
    assert IntentClassifier(p, lambda: "m").classify("hi") is Intent.CHAT


def test_provider_error_falls_back_to_chat():
    class Boom:
        def chat(self, *a, **kw):
            raise RuntimeError("network down")

    assert IntentClassifier(Boom(), lambda: "m").classify("hi") is Intent.CHAT
