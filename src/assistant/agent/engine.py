import json
import uuid
from dataclasses import dataclass, field
from typing import Callable

from assistant.agent.recorder import TaskRecorder
from assistant.agent.safety import ConfirmCallback, ConfirmationRequest, Policy
from assistant.providers.base import ChatMessage, Provider
from assistant.tools.registry import ToolRegistry

EXECUTOR_SYSTEM = (
    "你是 assistant 的任务执行引擎。用提供的工具完成用户的目标。\n"
    "规则：\n"
    "1. 第一步先输出简要计划（3 行以内），随后调用工具逐步执行。\n"
    "2. 每步只调用必要的工具；观察结果后再决定下一步。\n"
    "3. 失败时分析原因、换一种方式重试。\n"
    "4. 全部完成后输出总结：做了什么、结果如何、有无遗留问题。\n"
    "5. 如实报告失败，绝不编造结果。\n"
    "6. 禁止破坏性操作（格式化磁盘、删除系统文件、修改注册表等），"
    "除非用户明确要求。\n"
    "7. 无法完成时直接说明原因。"
)


@dataclass
class AgentEvent:
    type: str
    payload: dict = field(default_factory=dict)


@dataclass
class TaskReport:
    success: bool
    summary: str
    steps: list[dict] = field(default_factory=list)


class AgentEngine:
    MAX_STEPS = 12
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(
        self,
        provider: Provider,
        tools: ToolRegistry,
        model: Callable[[], str],
        policy: Policy,
        on_event: Callable[[AgentEvent], None] | None = None,
        confirm: ConfirmCallback | None = None,
        stop: Callable[[], bool] | None = None,
        recorder: TaskRecorder | None = None,
        thinking: Callable[[], str | None] | None = None,
    ):
        self.provider = provider
        self.tools = tools
        self.model = model
        self.policy = policy
        self.on_event = on_event or (lambda e: None)
        self.confirm = confirm or (lambda r: True)
        self.stop = stop or (lambda: False)
        self.recorder = recorder
        self.thinking = thinking

    def _thinking(self) -> str | None:
        return self.thinking() if self.thinking else None

    def _emit(self, etype: str, **payload) -> None:
        self.on_event(AgentEvent(etype, payload))

    def run_task(self, goal: str, session_id: str | None = None) -> TaskReport:
        task_id = uuid.uuid4().hex
        messages = [ChatMessage("system", EXECUTOR_SYSTEM),
                    ChatMessage("user", goal)]
        steps: list[dict] = []
        step_no = 0
        consecutive_failures = 0
        thinking = self._thinking()

        # ① 计划阶段（流式：思考与计划文本实时输出）
        plan = self.provider.chat(
            messages, model=self.model(), thinking=thinking,
            on_delta=lambda t: self._emit("text", text=t, phase="plan"),
            on_reasoning=lambda r: self._emit("reasoning", text=r))
        plan_text = plan.content.strip()
        self._emit("plan", goal=goal, plan=plan_text)
        if plan_text:
            messages.append(ChatMessage("assistant", plan_text))

        # ② 执行循环（流式：实时看到工具调用生成过程）
        tool_specs = self.tools.list_specs()
        for _ in range(self.MAX_STEPS):
            if self.stop():
                return self._finish(False, "任务已被用户手动停止。")
            tool_stream: dict[int, dict] = {}
            started: set[int] = set()

            def on_tool_delta(td):
                buf = tool_stream.setdefault(td.index,
                                             {"name": "", "args": ""})
                if td.name:
                    buf["name"] = td.name
                if td.arguments_delta:
                    buf["args"] += td.arguments_delta
                payload = {"index": td.index, "name": buf["name"],
                           "args": buf["args"],
                           "args_delta": td.arguments_delta}
                if td.index in started:
                    self._emit("tool_args", **payload)
                else:
                    started.add(td.index)
                    self._emit("tool_start", **payload)

            completion = self.provider.chat(
                messages, model=self.model(), tools=tool_specs,
                thinking=thinking,
                on_delta=lambda t: self._emit("text", text=t),
                on_reasoning=lambda r: self._emit("reasoning", text=r),
                on_tool_delta=on_tool_delta)
            if completion.tool_calls:
                step_no += 1
                record = {"step": step_no, "tool": None, "status": "unknown",
                          "output": ""}
                tool_msgs = []
                for tc in completion.tool_calls:
                    record["tool"] = tc.name
                    record["args"] = tc.arguments
                    self.on_event(AgentEvent(
                        "step_start", {"step": step_no, "tool": tc.name,
                                       "args": tc.arguments}))
                    tool, spec = self.tools.get(tc.name)
                    if self.policy.needs_confirmation(spec.risk):
                        request = ConfirmationRequest(
                            tool_name=tc.name, args=tc.arguments,
                            session_id=session_id)
                        if not self.confirm(request):
                            result_text = "用户拒绝了此操作。"
                            record["status"] = "declined"
                            record["output"] = result_text
                            tool_msgs.append(ChatMessage(
                                role="tool", content=result_text,
                                tool_call_id=tc.id))
                            self.on_event(AgentEvent(
                                "step_end", {"step": step_no,
                                             "tool": tc.name,
                                             "status": "declined"}))
                            continue
                    result = tool.execute(tc.name, tc.arguments)
                    result_text = json.dumps(
                        {"ok": result.ok, "output": result.output},
                        ensure_ascii=False)
                    record["status"] = "ok" if result.ok else "failed"
                    record["output"] = result.output[:2000]
                    if result.ok:
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                    tool_msgs.append(ChatMessage(
                        role="tool", content=result_text,
                        tool_call_id=tc.id))
                    self.on_event(AgentEvent(
                        "step_end", {"step": step_no, "tool": tc.name,
                                     "status": record["status"],
                                     "output": record["output"]}))
                steps.append(record)
                self._persist(task_id, session_id, step_no, record)
                # assistant 消息带上 tool_calls，再附 tool 结果
                messages.append(ChatMessage("assistant", "",
                                            tool_calls=completion.tool_calls))
                messages.extend(tool_msgs)
                if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                    return self._finish(
                        False, "连续多次失败，任务中止。请检查后重试或调整要求。")
            else:
                summary = completion.content.strip()
                if summary:
                    messages.append(ChatMessage("assistant", summary))
                self.on_event(AgentEvent("done", {"summary": summary}))
                return TaskReport(success=True, summary=summary,
                                  steps=steps)
        return self._finish(
            False, "达到最大执行步数，任务中止。")

    def _finish(self, success, summary):
        self.on_event(AgentEvent("failed", {"summary": summary}))
        return TaskReport(success=success, summary=summary)

    def _persist(self, task_id, session_id, step_no, record):
        if self.recorder and session_id:
            self.recorder.record(
                session_id=session_id, task_id=task_id, step_no=step_no,
                tool=record.get("tool"), args=record.get("args", {}),
                result=record.get("output", ""), status=record["status"])
