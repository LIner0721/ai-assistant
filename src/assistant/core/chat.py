import json
import logging
from typing import Callable, Protocol

from assistant.core.events import AgentEvent
from assistant.core.sessions import SessionManager
from assistant.core.tokens import estimate_tokens
from assistant.providers.base import ChatMessage, Provider

log = logging.getLogger("assistant.chat")


class SystemPromptFactory(Protocol):
    def __call__(self) -> str: ...


DEFAULT_PERSONA = (
    "你是 assistant，用户电脑上的私人 AI 助手。性格温和、可靠、偶尔幽默。"
    "回答用中文，简洁自然，像朋友一样。"
)

TOOL_GUIDANCE = (
    "你有工具可以操作电脑（文件、应用、命令、浏览器、系统信息），"
    "但只在用户明确要求时调用。规则：\n"
    "1. 调用工具前先简要说明要做什么。\n"
    "2. 每步只调用必要的工具；观察结果后再决定下一步。\n"
    "3. 失败时分析原因、换一种方式重试。\n"
    "4. 如实报告结果，绝不编造。\n"
    "5. 禁止破坏性操作（格式化磁盘、删除系统文件、修改注册表等），"
    "除非用户明确要求。\n"
    "6. 无法完成时直接说明原因。"
)

MEMORY_SECTION = "\n\n关于用户的长期记忆（仅供参考，不要主动提起）：\n{memories}"

OUTPUT_RESERVE = 4096
MAX_HISTORY_MESSAGES = 200


class ChatService:
    """统一 Agent 循环:每个消息都带工具清单,由模型决定是否调用。"""

    MAX_STEPS = 12
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(
        self,
        sessions: SessionManager,
        provider: Provider,
        model: Callable[[], str],
        system_prompt: SystemPromptFactory | None = None,
        retriever=None,      # MemoryRetriever | None
        extractor=None,      # MemoryExtractor | None
        resolver=None,       # MemoryResolver | None
        thinking: Callable[[], str | None] | None = None,
        tools=None,          # ToolRegistry | None
        policy=None,         # Policy | None
        confirm: Callable | None = None,
        stop: Callable[[], bool] | None = None,
        recorder=None,       # TaskRecorder | None
        context_limit: Callable[[], int] | None = None,
    ):
        self.sessions = sessions
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt or (lambda: DEFAULT_PERSONA)
        self.retriever = retriever
        self.extractor = extractor
        self.resolver = resolver
        self.thinking = thinking
        self.tools = tools
        self.policy = policy
        self.confirm = confirm or (lambda r: True)
        self.stop = stop or (lambda: False)
        self.recorder = recorder
        self.context_limit = context_limit or (lambda: 65536)

    # --- 上下文构建(按 token 预算裁剪历史) ---
    def _tool_specs_cost(self) -> int:
        if not self.tools:
            return 0
        specs = json.dumps(self.tools.list_specs(),
                           ensure_ascii=False, default=str)
        return estimate_tokens(specs)

    def _system_text(self, user_text: str) -> str:
        base = self.system_prompt()
        if self.tools:
            base += "\n\n" + TOOL_GUIDANCE
        if self.retriever:
            memories = self.retriever.retrieve(user_text, k=8)
            if memories:
                lines = "\n".join(f"- {m.content}" for m in memories)
                base += MEMORY_SECTION.format(memories=lines)
        return base

    def _build_messages(self, session_id: str, user_text: str,
                        user_msg: ChatMessage) -> list[ChatMessage]:
        system = ChatMessage("system", self._system_text(user_text))
        fixed_cost = (estimate_tokens(system.content)
                      + self._tool_specs_cost() + OUTPUT_RESERVE)
        limit = self.context_limit()
        messages = [system]
        used = 0
        for msg in reversed(self.sessions.history(session_id)
                            [-MAX_HISTORY_MESSAGES:]):
            cost = estimate_tokens(msg.content)
            if used + cost + fixed_cost > limit:
                break
            messages.append(msg)
            used += cost
        messages.append(user_msg)
        head, tail = messages[0], messages[1:]
        tail.reverse()
        return [head] + tail

    # --- 统一循环 ---
    def stream_reply(
        self,
        session_id: str,
        user_text: str,
        on_delta: Callable[[str], None],
        on_reasoning: Callable[[str], None] | None = None,
        on_event: Callable[[AgentEvent], None] | None = None,
    ) -> str:
        self.sessions.add_message(session_id, "user", user_text)
        user_msg = ChatMessage("user", user_text)
        messages = self._build_messages(session_id, user_text, user_msg)
        thinking = self.thinking() if self.thinking else None
        tool_specs = self.tools.list_specs() if self.tools else None
        step_no = 0
        consecutive_failures = 0

        for _ in range(self.MAX_STEPS):
            if self.stop():
                summary = "任务已被用户手动停止。"
                self._emit(on_event, "failed", summary=summary)
                return summary

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
                    self._emit(on_event, "tool_args", **payload)
                else:
                    started.add(td.index)
                    self._emit(on_event, "tool_start", **payload)

            completion = self.provider.chat(
                messages, model=self.model(), tools=tool_specs,
                on_delta=on_delta, on_reasoning=on_reasoning,
                on_tool_delta=on_tool_delta, thinking=thinking)

            if not completion.tool_calls:
                reply = completion.content
                if reply:
                    self.sessions.add_message(session_id, "assistant", reply)
                    self._update_memories(session_id, user_text, reply)
                self._emit(on_event, "done", summary=reply)
                return reply

            step_no += 1
            tool_msgs = []
            for tc in completion.tool_calls:
                record = {"step": step_no, "tool": tc.name,
                          "status": "unknown", "output": ""}
                self._emit(on_event, "step_start", step=step_no,
                           tool=tc.name, args=tc.arguments)
                tool, spec = self.tools.get(tc.name)

                if self.policy and self.policy.needs_confirmation(spec.risk):
                    from assistant.agent.safety import ConfirmationRequest
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
                        self._emit(on_event, "step_end", step=step_no,
                                   tool=tc.name, status="declined")
                        self._persist(session_id, step_no, record)
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
                    role="tool", content=result_text, tool_call_id=tc.id))
                log.info("tool %s ok=%s output=%r", tc.name, result.ok,
                         result.output[:200])
                self._emit(on_event, "step_end", step=step_no,
                           tool=tc.name, status=record["status"],
                           output=record["output"])
                self._persist(session_id, step_no, record)

            messages.append(ChatMessage("assistant", "",
                                        tool_calls=completion.tool_calls))
            messages.extend(tool_msgs)

            if consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                summary = "连续多次失败，任务中止。请检查后重试或调整要求。"
                self._emit(on_event, "failed", summary=summary)
                return summary

        summary = "达到最大执行步数，任务中止。"
        self._emit(on_event, "failed", summary=summary)
        return summary

    # --- 辅助 ---
    @staticmethod
    def _emit(on_event, etype: str, **payload) -> None:
        if on_event:
            on_event(AgentEvent(etype, payload))

    def _persist(self, session_id, step_no, record) -> None:
        if self.recorder and session_id:
            self.recorder.record(
                session_id=session_id, task_id="", step_no=step_no,
                tool=record.get("tool"), args=record.get("args", {}),
                result=record.get("output", ""), status=record["status"])

    def _update_memories(self, session_id, user_text, reply) -> None:
        if not (self.extractor and self.resolver):
            return
        try:
            candidates = self.extractor.extract([
                ChatMessage("user", user_text),
                ChatMessage("assistant", reply),
            ])
            if candidates:
                self.resolver.apply(candidates, source_session=session_id)
        except Exception:
            pass  # 记忆沉淀失败不影响聊天
