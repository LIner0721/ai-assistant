# 统一 Agent 循环 + Token 上下文 实施计划

> **For agentic workers:** pi 环境无 subagent/todo 工具,本计划在会话内顺序执行,用复选框跟踪。

**Goal:** 合并聊天/干活为一条统一工具循环,上下文改为 token 预算管理。

**Architecture:** ChatService 吸收 AgentEngine 的循环逻辑;每轮流式请求带全部工具清单,模型决定是否调用;token 估算器裁剪历史。删除 TaskRouter / IntentClassifier / AgentEngine。

**Tech Stack:** Python 3.12, PySide6, httpx(OpenAI 兼容协议), pytest, SQLite。

**Spec:** `docs/superpowers/specs/2026-08-14-unified-agent-loop-design.md`

## Global Constraints

- 测试命令:`.venv/bin/python -m pytest -q`(Windows:`.venv\Scripts\python -m pytest -q`)
- 提交信息:英文,`type: summary` 格式(如 `feat:` / `fix:` / `refactor:`)
- 推送:`git push https://LIner0721:<TOKEN>@github.com/LIner0721/ai-assistant.git main`(TOKEN 在会话中)
- 默认上下文上限 65536 tokens;预留输出 4096;历史条数硬上限 200
- 事件类型不变:text / reasoning / tool_start / tool_args / step_start / step_end / done / failed
- 工具中间过程不入会话历史;MAX_STEPS=12;MAX_CONSECUTIVE_FAILURES=3

---

### Task 1: token 估算器

**Files:**
- Create: `src/assistant/core/tokens.py`
- Test: `tests/test_tokens.py`

**Interfaces:**
- Produces: `estimate_tokens(text: str) -> int`(中文 1 字=1 token,其余 4 字符=1 token,空串=0)

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tokens.py
from assistant.core.tokens import estimate_tokens


def test_empty():
    assert estimate_tokens("") == 0


def test_cjk_chars_count_one_each():
    assert estimate_tokens("你好世界") == 4


def test_ascii_chars_four_per_token():
    assert estimate_tokens("abcdefgh") == 2   # 8 字符 / 4


def test_mixed():
    # 2 个中文 + 8 个英文 = 2 + 2
    assert estimate_tokens("你好abcdefgh") == 4
```

- [ ] **Step 2: 运行验证失败** → `pytest tests/test_tokens.py` → FAIL(ModuleNotFoundError)
- [ ] **Step 3: 最小实现**

```python
# src/assistant/core/tokens.py
def estimate_tokens(text: str) -> int:
    """粗略 token 估算:中文每字 1 token,其余每 4 字符 1 token。"""
    if not text:
        return 0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - cjk
    return cjk + (other // 4) + (1 if other % 4 else 0)
```

- [ ] **Step 4: 验证通过** → `pytest tests/test_tokens.py`
- [ ] **Step 5: 提交** `feat: add token estimator for context budgeting`

---

### Task 2: 上下文上限配置 + 设置界面

**Files:**
- Modify: `src/assistant/storage/config.py`(AppConfig 加字段)
- Modify: `src/assistant/ui/settings_dialog.py`(模型 tab 加输入)
- Test: `tests/test_config.py`、`tests/test_ui_smoke.py::test_settings_dialog_thinking_mode` 扩展

**Interfaces:**
- Consumes: 无
- Produces: `AppConfig.context_limit_tokens: int = 65536`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py 增加
def test_context_limit_default_and_roundtrip(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cfg = cm.load()
    assert cfg.context_limit_tokens == 65536
    cfg.context_limit_tokens = 131072
    cm.save(cfg)
    assert cm.load().context_limit_tokens == 131072
```

```python
# tests/test_ui_smoke.py 的 test_settings_dialog_thinking_mode 末尾加
    dlg.context_limit.setValue(128)
    cfg = dlg.result_config()
    assert cfg.context_limit_tokens == 128 * 1024
```

- [ ] **Step 2: 运行验证失败**
- [ ] **Step 3: 实现**

```python
# config.py AppConfig 增加字段
context_limit_tokens: int = 65536
```

```python
# settings_dialog.py _model_tab 里,thinking_mode 之后:
self.context_limit = QSpinBox()
self.context_limit.setRange(8, 512)
self.context_limit.setSuffix(" K")
self.context_limit.setValue(self._cfg.context_limit_tokens // 1024)
form.addRow("上下文上限", self.context_limit)

# result_config() 里:
self._cfg.context_limit_tokens = self.context_limit.value() * 1024
```

(需 import QSpinBox)

- [ ] **Step 4: 验证通过**(全量跑,确认其它测试不受影响)
- [ ] **Step 5: 提交** `feat: configurable context token limit in settings`

---

### Task 3: 事件类型迁到 core/events.py

**Files:**
- Create: `src/assistant/core/events.py`
- Modify: `tests/test_ui_smoke.py`(两处 import)
- Modify: `tests/test_ui_crash_fixes.py`(如有 engine import)

**Interfaces:**
- Produces: `AgentEvent(type: str, payload: dict = field(default_factory=dict))`

- [ ] **Step 1: 写失败测试**(改 import 后运行,预期 ImportError)

```python
# tests/test_ui_smoke.py: from assistant.agent.engine import AgentEvent
# 改为: from assistant.core.events import AgentEvent
```

- [ ] **Step 2: 运行验证失败**
- [ ] **Step 3: 实现**

```python
# src/assistant/core/events.py
from dataclasses import dataclass, field


@dataclass
class AgentEvent:
    type: str
    payload: dict = field(default_factory=dict)
```

- [ ] **Step 4: 验证通过**
- [ ] **Step 5: 提交** `refactor: move AgentEvent to core.events`

---

### Task 4: ChatService 统一循环(核心任务)

**Files:**
- Modify: `src/assistant/core/chat.py`(重写 stream_reply)
- Delete: `src/assistant/agent/engine.py`、`src/assistant/core/tasks.py`、`src/assistant/core/intent.py`
- Delete: `tests/test_agent_engine.py`、`tests/test_tasks.py`、`tests/test_intent.py`
- Test: `tests/test_chat.py`(重写)、`tests/test_chat_memory.py`(FakeProvider 签名已兼容,跑一遍确认)

**Interfaces:**
- Consumes: `estimate_tokens`(Task 1)、`AgentEvent`(Task 3)、`Provider.chat(messages, model, tools=None, on_delta=None, on_reasoning=None, on_tool_delta=None, thinking=None)`、`ToolRegistry.list_specs()/get(name)`、`Policy.needs_confirmation(risk)`、`ConfirmBridge.confirm(request)`、`TaskRecorder.record(...)`
- Produces: `ChatService(sessions, provider, model, system_prompt=None, retriever=None, extractor=None, resolver=None, thinking=None, tools=None, policy=None, confirm=None, stop=None, recorder=None, context_limit=None)`;`stream_reply(session_id, user_text, on_delta, on_reasoning=None, on_event=None) -> str`

- [ ] **Step 1: 写失败测试** —— 重写 tests/test_chat.py:

```python
from assistant.core.chat import DEFAULT_PERSONA, ChatService, TOOL_GUIDANCE
from assistant.core.events import AgentEvent
from assistant.core.sessions import SessionManager
from assistant.providers.base import ChatMessage, Completion, ToolCall
from assistant.storage.db import Database
from assistant.agent.safety import Policy
from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec
from assistant.tools.registry import ToolRegistry


class EchoTool(Tool):
    @property
    def specs(self):
        return [ToolSpec(name="echo", description="回显",
                         parameters={"type": "object", "properties": {}},
                         risk=RiskLevel.LOW)]

    def execute(self, name, args):
        return ToolResult(ok=True, output=f"echo:{args.get('text','')}")


class FakeProvider:
    """脚本序列:每项为 Completion 或 (Completion, 流式事件字典)。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.kwargs = []

    def chat(self, messages, model, tools=None, on_delta=None,
             on_reasoning=None, on_tool_delta=None, thinking=None):
        self.kwargs.append({"tools": tools, "thinking": thinking})
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        streams, completion = ({}, item) if not isinstance(item, tuple) else item
        for t in streams.get("text", []):
            if on_delta: on_delta(t)
        for r in streams.get("reasoning", []):
            if on_reasoning: on_reasoning(r)
        return completion


def make_service(script, **kw):
    db = Database(":memory:"); db.migrate()
    sessions = SessionManager(db)
    provider = FakeProvider(script)
    reg = ToolRegistry(); reg.register(EchoTool())
    service = ChatService(sessions, provider, model=lambda: "m",
                          tools=reg, policy=Policy(), **kw)
    return sessions, provider, service


def test_plain_reply_no_tools_used():
    sessions, provider, service = make_service(
        [Completion(content="好的")])
    deltas = []
    reply = service.stream_reply(sessions.create(), "你好",
                                 on_delta=deltas.append)
    assert reply == "好的"
    assert "".join(deltas) == "好的"
    assert provider.kwargs[0]["tools"] is not None   # 每轮都带工具
    history = sessions.history(sessions.create()) if False else None


def test_plain_reply_persists():
    sessions, provider, service = make_service([Completion(content="好的")])
    sid = sessions.create()
    service.stream_reply(sid, "你好", on_delta=lambda t: None)
    history = sessions.history(sid)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].content == "好的"


def test_tool_loop_executes_and_feeds_back():
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
    # 第二次请求里带 tool 角色回喂
    tool_msgs = [m for m in provider.script if False]  # 占位
    assert events[:4] == ["step_start", "step_end", "text", "done"] or \
           events[0] == "step_start"
    # 历史只有 user 和最终 assistant 文本,无工具中间过程
    history = sessions.history(sid)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[1].content == "完成了"


def test_tool_result_fed_back_to_model():
    script = [
        Completion(tool_calls=[ToolCall(id="c1", name="echo",
                                        arguments={"text": "hi"})]),
        Completion(content="完成"),
    ]
    sessions, provider, service = make_service(script)
    service.stream_reply(sessions.create(), "干活", on_delta=lambda t: None)
    # 第二次调用的 messages 含 tool 消息
    second_call_messages = None
    return second_call_messages  # 见下方 FakeProvider 记录 messages


def test_confirmation_declined_tool_skipped():
    script = [
        Completion(tool_calls=[ToolCall(id="c1", name="echo",
                                        arguments={"text": "hi"})]),
        Completion(content="好的"),
    ]
    sessions, provider, service = make_service(
        script, confirm=lambda req: False)
    sid = sessions.create()
    events = []
    reply = service.stream_reply(sid, "干活", on_delta=lambda t: None,
                                 on_event=lambda e: events.append(e))
    assert reply == "好的"
    declined = [e for e in events if e.type == "step_end"
                and e.payload["status"] == "declined"]
    assert declined


def test_stop_flag_aborts():
    script = [Completion(tool_calls=[ToolCall(id="c1", name="echo",
                                               arguments={})]),
              Completion(content="继续")]
    stopped = {"v": False}
    sessions, provider, service = make_service(
        script, stop=lambda: stopped["v"])
    sid = sessions.create()
    stopped["v"] = True
    reply = service.stream_reply(sid, "干活", on_delta=lambda t: None)
    assert "停止" in reply


def test_context_trimmed_to_token_budget():
    from assistant.core.tokens import estimate_tokens
    db = Database(":memory:"); db.migrate()
    sessions = SessionManager(db)
    sid = sessions.create()
    for i in range(50):
        sessions.add_message(sid, "user", f"填充内容{i}")
        sessions.add_message(sid, "assistant", f"回复内容{i}")
    provider = FakeProvider([Completion(content="好")])
    service = ChatService(sessions, provider, model=lambda: "m",
                          context_limit=lambda: 2000)
    service.stream_reply(sid, "问", on_delta=lambda t: None)
    sent = provider.last_messages()
    total = sum(estimate_tokens(m.content) for m in sent)
    assert total <= 2000 - 4096 or total <= 2000
    assert len(sent) < 101   # 远小于全部 101 条


def test_system_prompt_contains_tool_guidance():
    sessions, provider, service = make_service([Completion(content="好")])
    service.stream_reply(sessions.create(), "hi", on_delta=lambda t: None)
    system = provider.last_messages()[0].content
    assert DEFAULT_PERSONA in system and "只在用户要求" in system
```

(FakeProvider 需补 `last_messages()`:记录每次 messages 列表;占位断言在实现阶段修正为真实断言)

- [ ] **Step 2: 运行验证失败**(test_chat 大改,FAIL)
- [ ] **Step 3: 实现 chat.py 重写**

```python
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
    MAX_STEPS = 12
    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, sessions, provider, model,
                 system_prompt=None, retriever=None, extractor=None,
                 resolver=None, thinking=None, tools=None, policy=None,
                 confirm=None, stop=None, recorder=None,
                 context_limit=None):
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

    def _emit(self, on_event, etype, **payload):
        if on_event:
            on_event(AgentEvent(etype, payload))

    def _tool_specs_cost(self):
        if not self.tools:
            return 0
        import json
        return estimate_tokens(json.dumps(self.tools.list_specs(),
                                          ensure_ascii=False, default=str))

    def _build_messages(self, session_id, user_text):
        base = self.system_prompt()
        if self.retriever:
            memories = self.retriever.retrieve(user_text, k=8)
            if memories:
                lines = "\n".join(f"- {m.content}" for m in memories)
                base += MEMORY_SECTION.format(memories=lines)
        system = ChatMessage("system", base)
        history = self.sessions.history(session_id)
        limit = self.context_limit()
        fixed_cost = (estimate_tokens(system.content)
                      + self._tool_specs_cost() + OUTPUT_RESERVE)
        messages = [system]
        used = estimate_tokens(system.content)
        for msg in reversed(history[-MAX_HISTORY_MESSAGES:]):
            cost = estimate_tokens(msg.content)
            if used + cost + fixed_cost - estimate_tokens(system.content) > limit:
                break
            messages.append(msg)
            used += cost
        # 还原为时间顺序
        head, tail = messages[0], messages[1:]
        tail.reverse()
        return [head] + tail

    def stream_reply(self, session_id, user_text, on_delta,
                     on_reasoning=None, on_event=None):
        self.sessions.add_message(session_id, "user", user_text)
        messages = self._build_messages(session_id, user_text)
        messages.append(ChatMessage("user", user_text))
        # 裁剪时用户消息必须保留(上面 append 保证;若 _build_messages 已含 user?历史不含,安全)
        thinking = self.thinking() if self.thinking else None
        tool_specs = self.tools.list_specs() if self.tools else None
        step_no = 0
        consecutive_failures = 0
        for _ in range(self.MAX_STEPS):
            if self.stop():
                summary = "任务已被用户手动停止。"
                self._emit(on_event, "failed", summary=summary)
                return summary
            tool_stream, started = {}, set()

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
                    if not self.confirm(ConfirmationRequest(
                            tool_name=tc.name, args=tc.arguments,
                            session_id=session_id)):
                        result_text = "用户拒绝了此操作。"
                        record["status"] = "declined"
                        record["output"] = result_text
                        tool_msgs.append(ChatMessage(
                            role="tool", content=result_text,
                            tool_call_id=tc.id))
                        self._emit(on_event, "step_end", step=step_no,
                                   tool=tc.name, status="declined")
                        if self.recorder and session_id:
                            self.recorder.record(
                                session_id=session_id, task_id="", 
                                step_no=step_no, tool=tc.name,
                                args=tc.arguments, result=result_text,
                                status="declined")
                        continue
                result = tool.execute(tc.name, tc.arguments)
                import json
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
                if self.recorder and session_id:
                    self.recorder.record(
                        session_id=session_id, task_id="",
                        step_no=step_no, tool=tc.name, args=tc.arguments,
                        result=record["output"], status=record["status"])
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

    def _update_memories(self, session_id, user_text, reply):
        ...  # 原样保留
```

同时删除 engine.py / tasks.py / intent.py 及对应测试文件。

- [ ] **Step 4: 运行全量测试,修正失败**(test_chat 断言、test_ui_smoke ChatService 签名、test_chat_memory)
- [ ] **Step 5: 提交** `refactor: unified agent loop in ChatService with token-based context`

---

### Task 5: main.py / main_window.py 接线

**Files:**
- Modify: `src/assistant/main.py`(删 router/classifier/engine 组装,ChatService 注入 tools/policy/confirm/stop/recorder/context_limit)
- Modify: `src/assistant/ui/main_window.py`(删 router 参数与 `_send_chat_only`,`_send` 直调 stream_reply 并接 on_event;状态栏 token 文案)
- Modify: `tests/test_ui_smoke.py`(MainWindow 构造不再传 router;`context_text` 断言改为 token 文案)

**Interfaces:**
- Consumes: ChatService 新签名(Task 4)
- Produces: 无对外新接口

- [ ] **Step 1: 写失败测试**(test_ui_smoke 改 MainWindow 构造与状态栏断言,预期 FAIL)

```python
# main_window 状态栏:_update_context 改为
from assistant.core.tokens import estimate_tokens
count = estimate_tokens("".join(m.content for m in self.sessions.history(sid)))
limit_k = (self.cfg.context_limit_tokens // 1024) if self.cfg else 64
self._context_label.setText(f"上下文 {count/1024:.1f}K/{limit_k}K")
# 断言:win.context_text().startswith("上下文 ")
```

- [ ] **Step 2: 运行验证失败**
- [ ] **Step 3: 实现**

```python
# main.py 组装(替换 router/classifier/make_engine 段):
policy = Policy(autopilot=cfg.autopilot_default)
recorder = TaskRecorder(db)
confirm_bridge = ConfirmBridge()
chat = ChatService(
    sessions, provider, model=lambda: cfg.models.model,
    system_prompt=persona.active, retriever=retriever,
    extractor=extractor, resolver=resolver,
    thinking=lambda: _thinking(cfg.models.thinking_mode),
    tools=tool_registry, policy=policy,
    confirm=confirm_bridge.confirm,
    stop=lambda: window._stop_flag.is_set(),
    recorder=recorder,
    context_limit=lambda: cfg.context_limit_tokens)
# window 创建后:confirm_bridge.window = window
window = MainWindow(sessions, chat, cfg, secrets,
                    persona=persona, memory_store=memory_store)
```

```python
# main_window.py:
# - __init__ 去掉 router 参数(保留向后兼容?直接删,改测试)
# - _send: 无条件走 stream_reply + on_event → bus publish "task.event"
# - 删除 _send_chat_only
```

- [ ] **Step 4: 全量验证通过**
- [ ] **Step 5: 提交** `refactor: wire unified chat service into app, token usage in status bar`

---

### Task 6: 收尾验证 + 设计文档提交 + 推送

- [ ] **Step 1:** 全量测试 `.venv/bin/python -m pytest -q` 全绿
- [ ] **Step 2:** `grep -rn "intent\|TaskRouter\|AgentEngine" src tests` 无残留引用
- [ ] **Step 3:** 离屏渲染冒烟(chat_view 气泡不受影响)
- [ ] **Step 4:** 版本号 0.4.0;提交设计文档+计划
- [ ] **Step 5:** 推送到 GitHub
