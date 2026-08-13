from assistant.providers.base import ChatMessage, ToolCall
from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec
from assistant.tools.registry import ToolRegistry


def test_message_with_tool_calls_roundtrip():
    msg = ChatMessage(
        role="assistant", content="",
        tool_calls=[ToolCall(id="c1", name="read_file",
                             arguments={"path": "a.txt"})])
    d = msg.to_openai()
    assert d["tool_calls"][0]["id"] == "c1"
    assert d["tool_calls"][0]["type"] == "function"
    assert d["tool_calls"][0]["function"]["name"] == "read_file"
    assert '"path": "a.txt"' in d["tool_calls"][0]["function"]["arguments"]


def test_tool_role_message_has_tool_call_id():
    msg = ChatMessage(role="tool", content="结果", tool_call_id="c1")
    d = msg.to_openai()
    assert d["tool_call_id"] == "c1"


def test_plain_message_unchanged():
    d = ChatMessage(role="user", content="hi").to_openai()
    assert d == {"role": "user", "content": "hi"}


class FakeTool(Tool):
    @property
    def specs(self):
        return [ToolSpec(name="do_thing", description="做一件事",
                         parameters={"type": "object", "properties": {}},
                         risk=RiskLevel.LOW)]

    def execute(self, name, args):
        return ToolResult(ok=True, output="done")


def test_registry_specs_openai_format():
    reg = ToolRegistry()
    reg.register(FakeTool())
    specs = reg.list_specs()
    assert specs[0]["type"] == "function"
    assert specs[0]["function"]["name"] == "do_thing"
    assert reg.risk_of("do_thing") is RiskLevel.LOW


def test_registry_unknown_tool():
    import pytest
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")
