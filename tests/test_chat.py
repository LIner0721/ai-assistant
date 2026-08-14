from assistant.agent.safety import Policy
from assistant.core.chat import DEFAULT_PERSONA, TOOL_GUIDANCE, ChatService
from assistant.core.sessions import SessionManager
from assistant.providers.base import ChatMessage, Completion, ToolCall
from assistant.storage.db import Database
from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec
from assistant.tools.registry import ToolRegistry


class EchoTool(Tool):
    @property
    def specs(self):
        return [ToolSpec(name="echo", description="回显输入",
                         parameters={"type": "object", "properties": {}},
                         risk=RiskLevel.LOW)]

    def execute(self, name, args):
        return ToolResult(ok=True, output=f"echo:{args.get('text', '')}")


class FlakyTool(Tool):
    @property
    def specs(self):
        return [ToolSpec(name="flaky", description="总是失败",
                         parameters={"type": "object", "properties": {}},
                         risk=RiskLevel.LOW)]

    def execute(self, name, args):
        return ToolResult(ok=False, output="总是失败")


class HighRiskTool(Tool):
    @property
    def specs(self):
        return [ToolSpec(name="danger", description="危险操作",
                         parameters={"type": "object", "properties": {}},
                         risk=RiskLevel.HIGH)]

    def execute(self, name, args):
        return ToolResult(ok=True, output="危险完成")


class FakeProvider:
    """脚本序列:每项为 Completion 或 (流式回调字典, Completion)。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.kwargs = []
        self.messages_log = []

    def chat(self, messages, model, tools=None, on_delta=None,
             on_reasoning=None, on_tool_delta=None, thinking=None):
        self.messages_log.append(list(messages))
        self.kwargs.append({"tools": tools, "thinking": thinking})
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        streams, completion = ({}, item) if not isinstance(item, tuple) \
            else item
        if on_delta and not streams.get("text") and completion.content:
            for ch in completion.content:   # 真实 provider 会流式输出文本
                on_delta(ch)
        for t in streams.get("text", []):
            if on_delta:
                on_delta(t)
        for r in streams.get("reasoning", []):
            if on_reasoning:
                on_reasoning(r)
        return completion

    def last_messages(self):
        return self.messages_log[-1]


def make_service(script, **kw):
    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    provider = FakeProvider(script)
    reg = ToolRegistry()
    reg.register(EchoTool())
    service = ChatService(sessions, provider, model=lambda: "m",
                          tools=reg, policy=Policy(), **kw)
    return sessions, provider, service


def test_plain_reply_streams_and_persists():
    sessions, provider, service = make_service([Completion(content="好的")])
    deltas = []
    sid = sessions.create()
    reply = service.stream_reply(sid, "你好", on_delta=deltas.append)
    assert reply == "好的"
    assert "".join(deltas) == "好的"
    assert provider.kwargs[0]["tools"] is not None   # 每轮都带工具清单
    history = sessions.history(sid)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].content == "好的"


def test_tool_loop_executes_feeds_back_and_persists_only_final():
    script = [
        Completion(tool_calls=[ToolCall(id="c1", name="echo",
                                        arguments={"text": "hi"})]),
        ({"text": ["完成"]}, Completion(content="完成了")),
    ]
    sessions, provider, service = make_service(script)
    events = []
    sid = sessions.create()
    reply = service.stream_reply(sid, "干个活", on_delta=lambda t: None,
                                 on_event=lambda e: events.append(e.type))
    assert reply == "完成了"
    # 第二轮请求回喂了 tool 结果
    tool_msgs = [m for m in provider.messages_log[1] if m.role == "tool"]
    assert tool_msgs and "echo:hi" in tool_msgs[0].content
    # 事件序列:step_start/step_end 在 done 之前
    assert events[0] == "step_start"
    assert events[1] == "step_end"
    assert events[-1] == "done"
    # 历史只有 user 和最终文本,无工具中间过程
    history = sessions.history(sid)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].content == "完成了"


def test_confirmation_declined_skips_tool():
    script = [
        Completion(tool_calls=[ToolCall(id="c1", name="danger",
                                        arguments={})]),
        Completion(content="好的"),
    ]
    sessions, provider, service = make_service(
        script, confirm=lambda req: False)
    reg = ToolRegistry()
    reg.register(HighRiskTool())
    service.tools = reg
    events = []
    reply = service.stream_reply(sessions.create(), "干活",
                                 on_delta=lambda t: None,
                                 on_event=lambda e: events.append(e))
    assert reply == "好的"
    declined = [e for e in events if e.type == "step_end"
                and e.payload["status"] == "declined"]
    assert declined
    # 拒绝后仍回喂了 tool 消息
    tool_msgs = [m for m in provider.messages_log[1] if m.role == "tool"]
    assert tool_msgs and "拒绝" in tool_msgs[0].content


def test_stop_flag_aborts():
    script = [Completion(tool_calls=[ToolCall(id="c1", name="echo",
                                               arguments={})]),
              Completion(content="继续")]
    stopped = {"v": False}
    sessions, provider, service = make_service(script,
                                               stop=lambda: stopped["v"])
    stopped["v"] = True
    reply = service.stream_reply(sessions.create(), "干活",
                                 on_delta=lambda t: None)
    assert "停止" in reply


def test_consecutive_failures_abort():
    script = [Completion(tool_calls=[ToolCall(id="c" + str(i),
                                               name="flaky",
                                               arguments={})])
              for i in range(4)]
    sessions, provider, service = make_service(script)
    reg = ToolRegistry()
    reg.register(FlakyTool())
    service.tools = reg
    reply = service.stream_reply(sessions.create(), "干活",
                                 on_delta=lambda t: None)
    assert "失败" in reply
    assert provider.calls == 3   # 连续 3 次失败后中止


def test_max_steps_abort():
    script = [Completion(tool_calls=[ToolCall(id=f"c{i}", name="echo",
                                               arguments={})])
              for i in range(20)]
    sessions, provider, service = make_service(script)
    reply = service.stream_reply(sessions.create(), "干活",
                                 on_delta=lambda t: None)
    assert "最大执行步数" in reply
    assert provider.calls == 12


def test_context_trimmed_by_token_budget():
    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    sid = sessions.create()
    for i in range(50):
        sessions.add_message(sid, "user", f"填充内容第{i}条" * 10)
        sessions.add_message(sid, "assistant", f"回复内容第{i}条" * 10)
    provider = FakeProvider([Completion(content="好")])
    service = ChatService(sessions, provider, model=lambda: "m",
                          context_limit=lambda: 6000)
    service.stream_reply(sid, "问", on_delta=lambda t: None)
    sent = provider.last_messages()
    assert 3 <= len(sent) < 101            # 明显被裁剪
    assert sent[-1].content == "问"        # 最新用户消息保留
    assert sent[-2].content == f"回复内容第49条" * 10   # 最新历史保留
    assert not sent[1].content.startswith("填充内容第0条")  # 最旧已丢


def test_system_prompt_has_persona_and_tool_guidance():
    sessions, provider, service = make_service([Completion(content="好")])
    service.stream_reply(sessions.create(), "hi", on_delta=lambda t: None)
    system = provider.last_messages()[0].content
    assert DEFAULT_PERSONA in system
    assert TOOL_GUIDANCE in system
