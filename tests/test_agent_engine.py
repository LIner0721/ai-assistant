from assistant.agent.engine import AgentEngine, TaskReport
from assistant.agent.safety import Policy
from assistant.providers.base import (
    ChatMessage, Completion, ToolCall, ToolCallDelta,
)
from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec
from assistant.tools.registry import ToolRegistry


class EchoTool(Tool):
    @property
    def specs(self):
        return [ToolSpec(name="echo", description="回显输入",
                         parameters={"type": "object", "properties": {}},
                         risk=RiskLevel.LOW)]

    def execute(self, name, args):
        return ToolResult(ok=True, output=f"echo: {args.get('text', '')}")


class ScriptedProvider:
    """按脚本依次返回：第一次=计划文本，之后=工具调用或总结文本。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.messages_log = []

    def chat(self, messages, model, tools=None, on_delta=None,
             on_reasoning=None, on_tool_delta=None, thinking=None):
        self.messages_log.append(list(messages))
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(step, tuple):  # ("tool", name, args)
            return Completion(tool_calls=[ToolCall(id="c", name=step[1],
                                                   arguments=step[2])])
        return Completion(content=step)


class StreamingProvider:
    """按脚本返回，每个步骤可先触发流式回调再返回完成结果。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.kwargs = []

    def chat(self, messages, model, tools=None, on_delta=None,
             on_reasoning=None, on_tool_delta=None, thinking=None):
        self.kwargs.append({"thinking": thinking})
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        # ("stream", dict_of_deltas, completion)
        deltas, completion = step[1], step[2]
        for r in deltas.get("reasoning", []):
            if on_reasoning:
                on_reasoning(r)
        for t in deltas.get("text", []):
            if on_delta:
                on_delta(t)
        for td in deltas.get("tool_deltas", []):
            if on_tool_delta:
                on_tool_delta(td)
        return completion


def make_engine(script, **kw):
    provider = ScriptedProvider(script)
    reg = ToolRegistry()
    reg.register(EchoTool())
    engine = AgentEngine(provider, reg, model=lambda: "m", policy=Policy(),
                         **kw)
    return provider, reg, engine


def test_engine_streams_reasoning_text_and_tool_deltas():
    events = []
    provider = StreamingProvider([
        ("stream",
         {"reasoning": ["让我", "想想"], "text": ["计划", "：回显"]},
         Completion(content="计划：回显")),
        ("stream",
         {"tool_deltas": [
             ToolCallDelta(index=0, name="echo",
                           arguments_delta='{"text":'),
             ToolCallDelta(index=0, arguments_delta='"hi"}')]},
         Completion(tool_calls=[ToolCall(id="c", name="echo",
                                         arguments={"text": "hi"})])),
        ("stream",
         {"text": ["完成", "了"]},
         Completion(content="完成了")),
    ])
    reg = ToolRegistry()
    reg.register(EchoTool())
    engine = AgentEngine(provider, reg, model=lambda: "m", policy=Policy(),
                         on_event=lambda e: events.append((e.type, e.payload)))
    report = engine.run_task("测试任务")
    assert report.success is True
    types = [t for t, _ in events]
    # 思考与文本实时流出
    assert "".join(p["text"] for t, p in events if t == "reasoning") == "让我想想"
    text = "".join(p["text"] for t, p in events if t == "text")
    assert "计划：回显" in text and "完成了" in text
    # 工具调用增量实时流出，随后才执行
    assert types.index("tool_start") < types.index("step_start")
    assert types.index("tool_args") < types.index("step_start")
    tool_events = [p for t, p in events if t == "tool_start"]
    assert tool_events[0]["name"] == "echo"
    args_events = [p for t, p in events if t == "tool_args"]
    assert args_events[-1]["args"] == '{"text":"hi"}'
    assert args_events[0]["args_delta"] == '"hi"}'
    assert types[-1] == "done"


def test_engine_passes_thinking_to_provider():
    script = [("stream", {"text": ["完成"]}, Completion(content="完成"))]
    provider = StreamingProvider(script)
    reg = ToolRegistry()
    reg.register(EchoTool())
    engine = AgentEngine(provider, reg, model=lambda: "m", policy=Policy(),
                         thinking=lambda: "enabled")
    engine.run_task("测试")
    assert all(k["thinking"] == "enabled" for k in provider.kwargs)

    provider2 = StreamingProvider(script)
    engine2 = AgentEngine(provider2, reg, model=lambda: "m", policy=Policy())
    engine2.run_task("测试")
    assert all(k["thinking"] is None for k in provider2.kwargs)


def test_simple_task_plan_tool_summary():
    events = []
    provider, reg, engine = make_engine(
        ["计划：第一步调用 echo，然后总结。",
         ("tool", "echo", {"text": "hi"}),
         "已完成：回显成功。"],
        on_event=lambda e: events.append(e.type))
    report = engine.run_task("测试任务", session_id="s1")
    assert report.success is True
    assert "已完成" in report.summary
    assert len(report.steps) == 1
    assert report.steps[0]["tool"] == "echo"
    assert events[:3] == ["plan", "step_start", "step_end"]
    assert events[-1] == "done"
    # 工具结果以 tool 角色回喂给模型
    tool_msgs = [m for m in provider.messages_log[-1] if m.role == "tool"]
    assert tool_msgs and "echo: hi" in tool_msgs[0].content


def test_retries_after_failure():
    class FlakyTool(Tool):
        def __init__(self):
            self.fail_next = True

        @property
        def specs(self):
            return [ToolSpec(name="flaky", description="可能失败",
                             parameters={"type": "object", "properties": {}},
                             risk=RiskLevel.LOW)]

        def execute(self, name, args):
            if self.fail_next:
                self.fail_next = False
                return ToolResult(ok=False, output="暂时失败")
            return ToolResult(ok=True, output="成功")

    reg = ToolRegistry()
    tool = FlakyTool()
    reg.register(tool)
    provider = ScriptedProvider([
        "计划：调用 flaky。",
        ("tool", "flaky", {}),
        ("tool", "flaky", {}),   # 失败后模型换方案重试
        "重试后成功了。",
    ])
    engine = AgentEngine(provider, reg, model=lambda: "m", policy=Policy())
    report = engine.run_task("失败重试")
    assert report.success is True
    assert len(report.steps) == 2
    assert report.steps[0]["status"] == "failed"
    assert report.steps[1]["status"] == "ok"


def test_gives_up_after_max_failures():
    class AlwaysFailTool(Tool):
        @property
        def specs(self):
            return [ToolSpec(name="fail_tool", description="永远失败",
                             parameters={"type": "object", "properties": {}},
                             risk=RiskLevel.LOW)]

        def execute(self, name, args):
            return ToolResult(ok=False, output="就是失败")

    reg = ToolRegistry()
    reg.register(AlwaysFailTool())
    provider = ScriptedProvider([
        "计划：调用 fail_tool。",
        ("tool", "fail_tool", {}),
        ("tool", "fail_tool", {}),
        ("tool", "fail_tool", {}),
    ])
    engine = AgentEngine(provider, reg, model=lambda: "m", policy=Policy())
    report = engine.run_task("一直失败")
    assert report.success is False
    assert "连续多次失败" in report.summary


def test_high_risk_confirmation_declined():
    class DangerousTool(Tool):
        @property
        def specs(self):
            return [ToolSpec(name="delete_file", description="删文件",
                             parameters={"type": "object", "properties": {}},
                             risk=RiskLevel.HIGH)]

        def execute(self, name, args):
            return ToolResult(ok=True, output="deleted")

    reg = ToolRegistry()
    reg.register(DangerousTool())
    provider = ScriptedProvider([
        "计划：删除文件。",
        ("tool", "delete_file", {"path": "/x"}),
        "用户拒绝了删除操作，任务未执行。",
    ])
    requests = []
    engine = AgentEngine(
        provider, reg, model=lambda: "m", policy=Policy(),
        confirm=lambda r: (requests.append(r) or False))
    report = engine.run_task("删除")
    assert len(requests) == 1
    assert requests[0].tool_name == "delete_file"
    assert report.steps[0]["status"] == "declined"


def test_autopilot_skips_confirmation():
    class DangerousTool(Tool):
        @property
        def specs(self):
            return [ToolSpec(name="delete_file", description="删文件",
                             parameters={"type": "object", "properties": {}},
                             risk=RiskLevel.HIGH)]

        def execute(self, name, args):
            return ToolResult(ok=True, output="deleted")

    reg = ToolRegistry()
    reg.register(DangerousTool())
    provider = ScriptedProvider([
        "计划：删除文件。",
        ("tool", "delete_file", {"path": "/x"}),
        "删除完成。",
    ])
    engine = AgentEngine(provider, reg, model=lambda: "m",
                         policy=Policy(autopilot=True),
                         confirm=lambda r: (_ for _ in ()).throw(
                             AssertionError("不该要求确认")))
    report = engine.run_task("删除")
    assert report.success is True
    assert report.steps[0]["status"] == "ok"


def test_stop_interrupts():
    provider, reg, engine = make_engine(
        ["计划：开始。",
         ("tool", "echo", {"text": "1"}),
         "总结。"],
        stop=lambda: True)
    report = engine.run_task("被打断")
    assert report.success is False
    assert "停止" in report.summary
