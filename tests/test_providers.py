import json

import httpx

from assistant.providers.base import ChatMessage
from assistant.providers.openai_compat import OpenAICompatProvider
from assistant.providers.registry import ProviderRegistry


def _sse(payloads):
    lines = []
    for p in payloads:
        lines.append(f"data: {json.dumps(p)}")
    lines.append("data: [DONE]")
    return "\n\n".join(lines).encode("utf-8")


def test_non_stream_chat():
    def handler(request: httpx.Request):
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-chat"
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "你好"}}]
        })

    provider = OpenAICompatProvider("https://api.deepseek.com/v1", "sk-test")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    result = provider.chat([ChatMessage("user", "hi")], model="deepseek-chat")
    assert result.content == "你好"
    assert result.tool_calls == []


def test_stream_chat_deltas():
    def handler(request: httpx.Request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=_sse([
            {"choices": [{"delta": {"content": "你"}}]},
            {"choices": [{"delta": {"content": "好"}}]},
        ]))

    provider = OpenAICompatProvider("https://api.deepseek.com/v1", "sk-test")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    deltas = []
    result = provider.chat([ChatMessage("user", "hi")], model="deepseek-chat",
                           on_delta=deltas.append)
    assert "".join(deltas) == "你好"
    assert result.content == "你好"


def test_stream_tool_calls_accumulate():
    def handler(request: httpx.Request):
        return httpx.Response(200, content=_sse([
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1",
                 "function": {"name": "read_file", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "{\"path\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "\"a.txt\"}"}}]}}]},
        ]))

    provider = OpenAICompatProvider("https://api.deepseek.com/v1", "sk-test")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    result = provider.chat([ChatMessage("user", "read a.txt")],
                           model="deepseek-chat", on_delta=lambda t: None)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "a.txt"}


def test_stream_reasoning_deltas():
    def handler(request: httpx.Request):
        return httpx.Response(200, content=_sse([
            {"choices": [{"delta": {"reasoning_content": "让我"}}]},
            {"choices": [{"delta": {"reasoning_content": "想想"}}]},
            {"choices": [{"delta": {"content": "答案是 42"}}]},
        ]))

    provider = OpenAICompatProvider("https://api.deepseek.com/v1", "sk-test")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    reasoning, content = [], []
    result = provider.chat([ChatMessage("user", "hi")], model="deepseek-chat",
                           on_delta=content.append,
                           on_reasoning=reasoning.append)
    assert "".join(reasoning) == "让我想想"
    assert result.content == "答案是 42"
    assert "".join(content) == "答案是 42"


def test_stream_tool_call_deltas_reported():
    def handler(request: httpx.Request):
        return httpx.Response(200, content=_sse([
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1",
                 "function": {"name": "read_file", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "{\"path\":"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "\"a.txt\"}"}}]}}]},
        ]))

    provider = OpenAICompatProvider("https://api.deepseek.com/v1", "sk-test")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    deltas = []
    result = provider.chat([ChatMessage("user", "read a.txt")],
                           model="deepseek-chat", on_delta=lambda t: None,
                           on_tool_delta=deltas.append)
    assert len(deltas) == 3
    assert deltas[0].name == "read_file"
    assert deltas[1].arguments_delta == "{\"path\":"
    assert deltas[2].arguments_delta == "\"a.txt\"}"
    assert result.tool_calls[0].arguments == {"path": "a.txt"}


def test_thinking_param_sent():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "enabled"}
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        })

    provider = OpenAICompatProvider("https://api.deepseek.com/v1", "sk-test")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    provider.chat([ChatMessage("user", "hi")], model="deepseek-chat",
                  thinking="enabled")


def test_thinking_param_omitted_when_none():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        assert "thinking" not in body
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "ok"}}]
        })

    provider = OpenAICompatProvider("https://api.deepseek.com/v1", "sk-test")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    provider.chat([ChatMessage("user", "hi")], model="deepseek-chat")


def test_registry_creates_provider_and_rejects_unknown():
    import pytest
    reg = ProviderRegistry()
    p = reg.create("deepseek", "https://api.deepseek.com/v1", "sk-1")
    assert isinstance(p, OpenAICompatProvider)
    with pytest.raises(ValueError):
        reg.create("unknown-provider", "http://x", "sk-2")
