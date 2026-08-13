# Assistant 干活能力（工具 + Agent 引擎 + 安全模型）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Plan 1 的聊天应用基座上实现 B 级干活能力：工具集（files/apps/shell/browser）、C 级预留接口（computer）、安全确认模型、意图分类、多步 Agent 引擎与任务线 UI。

**Architecture:** `tools/` 提供统一 Tool 协议（JSON Schema 供模型 function calling）；`agent/` 提供 Plan→Act→Observe→Reflect 引擎（先出计划、再带工具循环执行、失败自纠上限 3 轮、全程事件回调）；`core/intent.py` 做聊天/任务双线路由；UI 用活动卡片呈现任务进度，高风险操作通过聊天流内嵌确认卡片。

**Tech Stack:** 复用 Plan 1 全部；新增 `trafilatura`（正文提取）、`playwright`（浏览器）、`pynput`（C 级预留）。

**Spec:** `docs/superpowers/specs/2026-08-13-windows-ai-assistant-design.md`
**依赖计划:** `docs/superpowers/plans/2026-08-13-assistant-platform-and-chat.md`

## Global Constraints

- Plan 1 全部约束继续生效（Python 3.12、SQLite 无 ORM、TDD、每任务 commit、线程模型）
- 工具执行全部同步、在 worker 线程调用；跨线程只走 EventBus + Qt 信号
- 高风控操作（写/删文件、执行命令、关进程）默认需确认；自动驾驶开启后放行但必须明示
- 命令执行：60s 超时、输出截断 8KB、禁交互等待
- 模型自纠上限 3 轮连续失败；全局停止信号任何时刻可中断
- C 级（键鼠）只留接口，v1 空实现，调用返回"未启用"错误

---

### Task 1: ChatMessage 支持 tool_calls + 工具协议与注册表

**Files:**
- Modify: `src/assistant/providers/base.py`
- Create: `src/assistant/tools/__init__.py`
- Create: `src/assistant/tools/base.py`
- Create: `src/assistant/tools/registry.py`
- Test: `tests/test_tools_base.py`

**Interfaces:**
- Consumes: `ToolCall`（Plan 1 已定义）
- Produces:
  - `ChatMessage` 扩展：`tool_calls: list[ToolCall] | None = None`、`tool_call_id: str | None = None`；`to_openai()` 包含 tool_calls（openai 格式）与 tool_call_id（tool 角色消息用）
  - `RiskLevel(Enum)`：`LOW = "low"`、`HIGH = "high"`
  - `ToolSpec(name: str, description: str, parameters: dict, risk: RiskLevel)`
  - `ToolResult(ok: bool, output: str, artifact: dict | None = None)`
  - `Tool`（ABC）：`specs: list[ToolSpec]`（property）、`execute(name: str, args: dict) -> ToolResult`
  - `ToolRegistry`：`register(tool: Tool)`、`get(name) -> tuple[Tool, ToolSpec]`、`list_specs() -> list[dict]`（OpenAI function calling 格式：`{"type": "function", "function": {...}}`）、`risk_of(name) -> RiskLevel`

- [ ] **Step 1: 写失败测试**

`tests/test_tools_base.py`:
```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_tools_base.py -v`
Expected: FAIL（`ChatMessage` 不接受 tool_calls）

- [ ] **Step 3: 修改 base.py 并实现工具协议**

`src/assistant/providers/base.py` 中 ChatMessage 改为:
```python
@dataclass
class ChatMessage:
    role: str
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    def to_openai(self) -> dict:
        m: dict = {"role": self.role, "content": self.content or ""}
        if self.tool_calls:
            m["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name,
                              "arguments": json.dumps(tc.arguments,
                                                      ensure_ascii=False)}}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            m["tool_call_id"] = self.tool_call_id
        return m
```
（文件顶部补 `import json`。）

`src/assistant/tools/base.py`:
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(Enum):
    LOW = "low"
    HIGH = "high"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict   # JSON Schema
    risk: RiskLevel


@dataclass
class ToolResult:
    ok: bool
    output: str
    artifact: dict | None = None


class Tool(ABC):
    @property
    @abstractmethod
    def specs(self) -> list[ToolSpec]: ...

    @abstractmethod
    def execute(self, name: str, args: dict) -> ToolResult: ...
```

`src/assistant/tools/registry.py`:
```python
from assistant.tools.base import RiskLevel, Tool, ToolSpec


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, tuple[Tool, ToolSpec]] = {}

    def register(self, tool: Tool) -> None:
        for spec in tool.specs:
            self._tools[spec.name] = (tool, spec)

    def get(self, name: str) -> tuple[Tool, ToolSpec]:
        return self._tools[name]

    def risk_of(self, name: str) -> RiskLevel:
        return self._tools[name][1].risk

    def list_specs(self) -> list[dict]:
        return [
            {"type": "function",
             "function": {"name": s.name, "description": s.description,
                          "parameters": s.parameters}}
            for _, s in sorted(self._tools.items())
        ]
```

`src/assistant/tools/__init__.py`（空文件）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_tools_base.py tests/test_chat.py -v`
Expected: 5 PASS + Plan 1 的 test_chat 3 PASS（回归）

- [ ] **Step 5: Commit**

```bash
git add src/assistant/providers/base.py src/assistant/tools tests/test_tools_base.py
git commit -m "feat: tool protocol, registry and tool-call message support"
```

---

### Task 2: files 工具

**Files:**
- Create: `src/assistant/tools/files.py`
- Test: `tests/test_tool_files.py`

**Interfaces:**
- Consumes: `Tool`/`ToolSpec`/`ToolResult`/`RiskLevel`
- Produces: `FilesTool`，7 个函数：
  - `read_file(path)`（LOW）—— 文件 >200KB 只读前 200KB 并注明截断
  - `write_file(path, content)`（HIGH）—— 覆盖写，自动建父目录
  - `list_dir(path)`（LOW）—— 返回条目名 + 类型（f/d）
  - `search_files(directory, pattern)`（LOW）—— rglob 匹配，上限 200 条
  - `file_info(path)`（LOW）—— 大小、修改时间、是否存在
  - `move_file(src, dst)`（HIGH）、`copy_file(src, dst)`（HIGH）、`delete_file(path)`（HIGH）
  - 全部函数返回 `ToolResult`，错误时 `ok=False` 且 output 为可读错误信息（不抛异常）

- [ ] **Step 1: 写失败测试（全部基于 tmp_path）**

`tests/test_tool_files.py`:
```python
from assistant.tools.files import FilesTool


def make(tmp_path):
    tool = FilesTool()
    d = tmp_path
    (d / "a.txt").write_text("hello", encoding="utf-8")
    (d / "sub").mkdir()
    (d / "sub" / "b.txt").write_text("world", encoding="utf-8")
    return tool, d


def test_read_file(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("read_file", {"path": str(d / "a.txt")})
    assert r.ok and r.output == "hello"


def test_write_file_creates_parents(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("write_file",
                     {"path": str(d / "x" / "y.txt"), "content": "新内容"})
    assert r.ok
    assert (d / "x" / "y.txt").read_text(encoding="utf-8") == "新内容"


def test_list_dir(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("list_dir", {"path": str(d)})
    assert r.ok
    assert "a.txt" in r.output and "sub/" in r.output


def test_search_files(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("search_files",
                     {"directory": str(d), "pattern": "*.txt"})
    assert r.ok
    assert "a.txt" in r.output and "b.txt" in r.output


def test_file_info_and_delete(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("file_info", {"path": str(d / "a.txt")})
    assert r.ok and "exists" in r.output
    r2 = tool.execute("delete_file", {"path": str(d / "a.txt")})
    assert r2.ok
    r3 = tool.execute("file_info", {"path": str(d / "a.txt")})
    assert "not exist" in r3.output


def test_move_file(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("move_file",
                     {"src": str(d / "a.txt"), "dst": str(d / "moved.txt")})
    assert r.ok
    assert (d / "moved.txt").exists() and not (d / "a.txt").exists()


def test_errors_return_not_ok(tmp_path):
    tool, d = make(tmp_path)
    r = tool.execute("read_file", {"path": str(d / "nope.txt")})
    assert not r.ok and "nope.txt" in r.output


def test_risks(tmp_path):
    tool, d = make(tmp_path)
    by_name = {s.name: s.risk for s in tool.specs}
    from assistant.tools.base import RiskLevel
    assert by_name["read_file"] is RiskLevel.LOW
    assert by_name["delete_file"] is RiskLevel.HIGH
    assert by_name["write_file"] is RiskLevel.HIGH
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_tool_files.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/tools/files.py`:
```python
from pathlib import Path

from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec

READ_LIMIT = 200 * 1024
SEARCH_LIMIT = 200


def _spec(name, desc, risk):
    return ToolSpec(name=name, description=desc,
                    parameters={"type": "object",
                                "properties": {"path": {"type": "string"}},
                                "required": ["path"]}, risk=risk)


class FilesTool(Tool):
    @property
    def specs(self):
        return [
            _spec("read_file", "读取文件内容（文本）。", RiskLevel.LOW),
            _spec("write_file", "写入/覆盖文件，自动创建父目录。",
                  RiskLevel.HIGH),
            _spec("list_dir", "列出目录内容（条目名 + f/d 标记）。",
                  RiskLevel.LOW),
            _spec("search_files", "按 glob 模式递归搜索文件。",
                  RiskLevel.LOW),
            _spec("file_info", "文件信息：存在性、大小、修改时间。",
                  RiskLevel.LOW),
            _spec("move_file", "移动/重命名文件。", RiskLevel.HIGH),
            _spec("copy_file", "复制文件。", RiskLevel.HIGH),
            _spec("delete_file", "删除文件。", RiskLevel.HIGH),
        ]

    def execute(self, name, args):
        try:
            return {
                "read_file": self._read,
                "write_file": self._write,
                "list_dir": self._list,
                "search_files": self._search,
                "file_info": self._info,
                "move_file": self._move,
                "copy_file": self._copy,
                "delete_file": self._delete,
            }[name](args)
        except Exception as exc:
            return ToolResult(ok=False, output=f"操作失败: {exc}")

    def _read(self, a):
        p = Path(a["path"])
        data = p.read_text(encoding="utf-8", errors="replace")
        if len(data) > READ_LIMIT:
            data = data[:READ_LIMIT] + "\n…(内容过长，已截断)"
        return ToolResult(ok=True, output=data)

    def _write(self, a):
        p = Path(a["path"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a["content"], encoding="utf-8")
        return ToolResult(ok=True, output=f"已写入 {p}")

    def _list(self, a):
        p = Path(a["path"])
        lines = []
        for item in sorted(p.iterdir()):
            lines.append(item.name + ("/" if item.is_dir() else ""))
        return ToolResult(ok=True, output="\n".join(lines) or "(空目录)")

    def _search(self, a):
        root = Path(a["directory"])
        found = [str(p) for p in root.rglob(a["pattern"])][:SEARCH_LIMIT]
        return ToolResult(ok=True,
                          output="\n".join(found) or "(无匹配)")

    def _info(self, a):
        p = Path(a["path"])
        if not p.exists():
            return ToolResult(ok=True, output=f"{p} 不存在")
        st = p.stat()
        return ToolResult(ok=True,
                          output=f"{p}: 存在, 大小 {st.st_size} 字节, "
                                 f"修改时间 {st.st_mtime:.0f}")

    def _move(self, a):
        src, dst = Path(a["src"]), Path(a["dst"])
        src.rename(dst)
        return ToolResult(ok=True, output=f"已移动 {src} -> {dst}")

    def _copy(self, a):
        import shutil
        src, dst = Path(a["src"]), Path(a["dst"])
        shutil.copy2(src, dst)
        return ToolResult(ok=True, output=f"已复制 {src} -> {dst}")

    def _delete(self, a):
        p = Path(a["path"])
        p.unlink()
        return ToolResult(ok=True, output=f"已删除 {p}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_tool_files.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/tools/files.py tests/test_tool_files.py
git commit -m "feat: files tool with high-risk operations flagged"
```

---

### Task 3: apps 工具

**Files:**
- Create: `src/assistant/tools/apps.py`
- Test: `tests/test_tool_apps.py`

**Interfaces:**
- Consumes: 工具协议
- Produces: `AppsTool`，2 个函数：
  - `launch_app(name_or_path)`（LOW）—— `shutil.which` 解析失败时 Windows 走 `cmd /c start`，其他平台走 `xdg-open`/`open`；成功返回"已启动"
  - `close_app(name)`（HIGH）—— Windows 用 `taskkill /F /IM`，其他平台用 `pkill -f`；进程不存在返回 `ok=False` 可读错误

- [ ] **Step 1: 写失败测试（monkeypatch 子进程）**

`tests/test_tool_apps.py`:
```python
import subprocess

from assistant.tools.apps import AppsTool
from assistant.tools.base import RiskLevel


def test_launch_resolves_from_path(monkeypatch, tmp_path):
    fake = tmp_path / "notepad"
    fake.write_text("#!/bin/sh\necho hi\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=":")
    tool = AppsTool()
    r = tool.execute("launch_app", {"name_or_path": "notepad"})
    assert r.ok and "已启动" in r.output


def test_close_app_windows_style(monkeypatch):
    import sys as _sys
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "SUCCESS: 已终止", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(_sys, "platform", "win32")  # 实现里用 sys.platform 判断
    tool = AppsTool()
    r = tool.execute("close_app", {"name": "notepad.exe"})
    assert r.ok
    assert any("taskkill" in c[0] for c in calls)


def test_close_app_missing_process(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 128, "", "没有找到进程")

    monkeypatch.setattr(subprocess, "run", fake_run)
    tool = AppsTool()
    r = tool.execute("close_app", {"name": "ghost.exe"})
    assert not r.ok


def test_risks():
    by_name = {s.name: s.risk for s in AppsTool().specs}
    assert by_name["launch_app"] is RiskLevel.LOW
    assert by_name["close_app"] is RiskLevel.HIGH
```

注意：`monkeypatch.setattr("os.name", "nt")` 无效（只读），改为实现里用 `sys.platform == "win32"`，测试 monkeypatch `sys.platform`。测试代码相应改为 `monkeypatch.setattr("sys", "platform", "win32")`。

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_tool_apps.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/tools/apps.py`:
```python
import shutil
import subprocess
import sys

from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec


class AppsTool(Tool):
    @property
    def specs(self):
        return [
            ToolSpec(name="launch_app", description="启动一个应用（可执行名或完整路径）。",
                     parameters={"type": "object",
                                 "properties": {"name_or_path": {"type": "string"}},
                                 "required": ["name_or_path"]},
                     risk=RiskLevel.LOW),
            ToolSpec(name="close_app", description="关闭一个正在运行的进程（进程名，如 notepad.exe）。",
                     parameters={"type": "object",
                                 "properties": {"name": {"type": "string"}},
                                 "required": ["name"]},
                     risk=RiskLevel.HIGH),
        ]

    def execute(self, name, args):
        try:
            if name == "launch_app":
                return self._launch(args["name_or_path"])
            if name == "close_app":
                return self._close(args["name"])
            return ToolResult(ok=False, output=f"未知函数: {name}")
        except Exception as exc:
            return ToolResult(ok=False, output=f"操作失败: {exc}")

    def _launch(self, target: str) -> ToolResult:
        resolved = shutil.which(target) or target
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", resolved],
                             shell=False)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", resolved])
        else:
            subprocess.Popen(["xdg-open", resolved])
        return ToolResult(ok=True, output=f"已启动 {target}")

    def _close(self, name: str) -> ToolResult:
        if sys.platform == "win32":
            cmd = ["taskkill", "/F", "/IM", name]
        else:
            cmd = ["pkill", "-f", name]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return ToolResult(ok=False,
                              output=f"关闭失败: {proc.stderr.strip() or '进程不存在'}")
        return ToolResult(ok=True, output=f"已关闭 {name}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_tool_apps.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/tools/apps.py tests/test_tool_apps.py
git commit -m "feat: apps tool for launching and closing processes"
```

---

### Task 4: shell 工具

**Files:**
- Create: `src/assistant/tools/shell.py`
- Test: `tests/test_tool_shell.py`

**Interfaces:**
- Consumes: 工具协议
- Produces: `ShellTool`，1 个函数：
  - `run_command(command)`（HIGH）—— Windows 经 `powershell -NoProfile -Command`，其他平台经 `sh -c`；60s 超时；stdout+stderr 拼接后截断 8KB；返回退出码与输出；超时返回 `ok=False`

- [ ] **Step 1: 写失败测试**

`tests/test_tool_shell.py`:
```python
import subprocess

from assistant.tools.shell import ShellTool
from assistant.tools.base import RiskLevel


def test_run_command_success(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        assert kw["timeout"] == 60
        return subprocess.CompletedProcess(cmd, 0, "hello world", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ShellTool().execute("run_command", {"command": "echo hi"})
    assert r.ok
    assert "hello world" in r.output
    assert "退出码 0" in r.output


def test_run_command_failure(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "command not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ShellTool().execute("run_command", {"command": "nope"})
    assert not r.ok
    assert "command not found" in r.output


def test_output_truncated(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, "x" * 20000, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ShellTool().execute("run_command", {"command": "big"})
    assert len(r.output) < 9000
    assert "截断" in r.output


def test_timeout(monkeypatch):
    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ShellTool().execute("run_command", {"command": "sleep 100"})
    assert not r.ok
    assert "超时" in r.output


def test_windows_uses_powershell(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("sys.platform", "win32")
    ShellTool().execute("run_command", {"command": "Get-Date"})
    assert calls[0][0] == "powershell"
    assert calls[0][1] == "-NoProfile"


def test_risk_high():
    assert ShellTool().specs[0].risk is RiskLevel.HIGH
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_tool_shell.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/tools/shell.py`:
```python
import subprocess
import sys

from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec

TIMEOUT = 60
OUTPUT_LIMIT = 8000


class ShellTool(Tool):
    @property
    def specs(self):
        return [
            ToolSpec(name="run_command", description="执行一条系统命令（Windows: PowerShell；其他: sh）。禁止交互式命令。",
                     parameters={"type": "object",
                                 "properties": {"command": {"type": "string"}},
                                 "required": ["command"]},
                     risk=RiskLevel.HIGH),
        ]

    def execute(self, name, args):
        try:
            if sys.platform == "win32":
                cmd = ["powershell", "-NoProfile", "-Command", args["command"]]
            else:
                cmd = ["sh", "-c", args["command"]]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, output=f"命令执行超时（>{TIMEOUT}s），已终止")
        except Exception as exc:
            return ToolResult(ok=False, output=f"命令执行失败: {exc}")

        output = (proc.stdout or "") + (proc.stderr or "")
        if len(output) > OUTPUT_LIMIT:
            output = output[:OUTPUT_LIMIT] + "\n…(输出过长，已截断)"
        ok = proc.returncode == 0
        head = "执行成功" if ok else "执行失败"
        return ToolResult(ok=ok, output=f"{head}（退出码 {proc.returncode}）\n{output}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_tool_shell.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/tools/shell.py tests/test_tool_shell.py
git commit -m "feat: shell tool with timeout and output truncation"
```

---

### Task 5: browser 工具（Playwright）

**Files:**
- Modify: `pyproject.toml`（dependencies 加 `playwright>=1.45`、`trafilatura>=1.8`）
- Create: `src/assistant/tools/browser.py`
- Test: `tests/test_tool_browser.py`

**Interfaces:**
- Consumes: 工具协议
- Produces: `BrowserTool`，2 个函数：
  - `search_web(query)`（LOW）—— Playwright 打开必应搜索，抓取最多 8 条结果（标题/链接/摘要）
  - `fetch_page(url)`（LOW）—— 打开页面、等待 DOMContentLoaded、取 HTML 交给 trafilatura 提取正文 Markdown；提取失败回退纯文本；上限 20KB 截断
  - 浏览器实例惰性启动（chromium headless），工具内做线程锁保护（Playwright sync API 必须在同一线程使用）

- [ ] **Step 1: 写失败测试（本地 HTTP 服务 + monkeypatch 搜索页面）**

`tests/test_tool_browser.py`:
```python
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def make_server(html):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def test_fetch_page_extracts_markdown():
    server = make_server(
        "<html><head><title>测试页</title></head>"
        "<body><h1>标题</h1><p>这是正文内容，包含重要信息。</p>"
        "<script>var x=1;</script></body></html>")
    try:
        from assistant.tools.browser import BrowserTool
        tool = BrowserTool()
        r = tool.execute("fetch_page",
                         {"url": f"http://127.0.0.1:{server.server_port}/"})
        assert r.ok
        assert "标题" in r.output
        assert "重要信息" in r.output
    finally:
        server.shutdown()


def test_fetch_page_http_error():
    server = make_server("<html><body>not found</body></html>")

    class H404(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    from assistant.tools.browser import BrowserTool
    tool = BrowserTool()
    r = tool.execute("fetch_page", {"url": "http://127.0.0.1:1/nothing"})
    assert not r.ok or "无法" in r.output
    server.shutdown()


def test_specs_low_risk():
    from assistant.tools.browser import BrowserTool
    from assistant.tools.base import RiskLevel
    assert all(s.risk is RiskLevel.LOW for s in BrowserTool().specs)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_tool_browser.py -v`
Expected: FAIL（依赖未装/模块不存在）

- [ ] **Step 3: 安装依赖**

Run: `.venv/bin/pip install -e ".[dev]" && .venv/bin/playwright install chromium`
Expected: 安装成功（chromium 约 100-200MB，下载到 `~/.cache/ms-playwright`）

- [ ] **Step 4: 实现**

`src/assistant/tools/browser.py`:
```python
import threading

import trafilatura
from playwright.sync_api import sync_playwright

from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec

FETCH_LIMIT = 20000
SEARCH_RESULT_LIMIT = 8


class BrowserTool(Tool):
    def __init__(self):
        self._lock = threading.Lock()
        self._pw = None
        self._browser = None

    def _ensure_browser(self):
        if self._browser is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)

    @property
    def specs(self):
        return [
            ToolSpec(name="search_web", description="搜索网页，返回结果列表（标题、链接、摘要）。",
                     parameters={"type": "object",
                                 "properties": {"query": {"type": "string"}},
                                 "required": ["query"]},
                     risk=RiskLevel.LOW),
            ToolSpec(name="fetch_page", description="打开网页并提取正文（Markdown）。",
                     parameters={"type": "object",
                                 "properties": {"url": {"type": "string"}},
                                 "required": ["url"]},
                     risk=RiskLevel.LOW),
        ]

    def execute(self, name, args):
        with self._lock:  # Playwright sync API 必须同一线程串行使用
            try:
                self._ensure_browser()
                if name == "search_web":
                    return self._search(args["query"])
                if name == "fetch_page":
                    return self._fetch(args["url"])
                return ToolResult(ok=False, output=f"未知函数: {name}")
            except Exception as exc:
                return ToolResult(ok=False, output=f"浏览器操作失败: {exc}")

    def _search(self, query: str) -> ToolResult:
        page = self._browser.new_page()
        try:
            page.goto(f"https://www.bing.com/search?q={query}",
                      timeout=30000)
            results = page.eval_on_selector_all(
                "li.b_algo",
                """els => els.slice(0, 8).map(el => {
                    const a = el.querySelector('h2 a');
                    const p = el.querySelector('p');
                    return {title: a ? a.innerText : '',
                            url: a ? a.href : '',
                            snippet: p ? p.innerText : ''};
                })""")
        finally:
            page.close()
        if not results:
            return ToolResult(ok=True, output="(没有搜到结果)")
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
        return ToolResult(ok=True, output="\n".join(lines))

    def _fetch(self, url: str) -> ToolResult:
        page = self._browser.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            html = page.content()
        finally:
            page.close()
        text = trafilatura.extract(html, output_format="markdown",
                                   include_comments=False)
        if not text:
            text = trafilatura.extract(html) or "(页面没有可提取的正文)"
        if len(text) > FETCH_LIMIT:
            text = text[:FETCH_LIMIT] + "\n…(内容过长，已截断)"
        return ToolResult(ok=True, output=text)

    def close(self):
        with self._lock:
            if self._browser:
                self._browser.close()
                self._pw.stop()
                self._browser = None
                self._pw = None
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_tool_browser.py -v`
Expected: 3 PASS（若本机无法联网下载 chromium，跳过并如实报告）

- [ ] **Step 6: Commit**

```bash
git add src/assistant/tools/browser.py tests/test_tool_browser.py pyproject.toml
git commit -m "feat: browser tool with search and content extraction"
```

---

### Task 6: computer 工具（C 级预留接口）

**Files:**
- Modify: `pyproject.toml`（dependencies 加 `pynput>=1.7`）
- Create: `src/assistant/tools/computer.py`
- Test: `tests/test_tool_computer.py`

**Interfaces:**
- Consumes: 工具协议
- Produces: `ComputerTool`，4 个函数（全部 HIGH，v1 空实现）：
  - `click(x, y)`、`type_text(text)`、`move_mouse(x, y)`、`screenshot(path)`
  - execute 返回 `ToolResult(ok=False, output="键鼠控制将在后续版本启用（C 级能力）")`
  - 提供 `click/type_text/move_mouse/screenshot` 方法骨架，v1.5 用 pynput 填充实现

- [ ] **Step 1: 写失败测试**

`tests/test_tool_computer.py`:
```python
from assistant.tools.computer import ComputerTool
from assistant.tools.base import RiskLevel


def test_specs_exist_and_high_risk():
    names = {s.name for s in ComputerTool().specs}
    assert {"click", "type_text", "move_mouse", "screenshot"} <= names
    assert all(s.risk is RiskLevel.HIGH for s in ComputerTool().specs)


def test_execute_returns_not_enabled():
    r = ComputerTool().execute("click", {"x": 10, "y": 20})
    assert not r.ok
    assert "后续版本" in r.output
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_tool_computer.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/tools/computer.py`:
```python
from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec

NOT_ENABLED = "键鼠控制将在后续版本启用（C 级能力）"


def _spec(name, desc):
    return ToolSpec(name=name, description=desc,
                    parameters={"type": "object", "properties": {}},
                    risk=RiskLevel.HIGH)


class ComputerTool(Tool):
    """C 级能力预留。v1 空实现；v1.5 起用 pynput 填充。"""

    @property
    def specs(self):
        return [
            _spec("click", "点击屏幕坐标 (x, y)。"),
            _spec("type_text", "输入文本到当前焦点窗口。"),
            _spec("move_mouse", "移动鼠标到 (x, y)。"),
            _spec("screenshot", "截取屏幕保存到文件。"),
        ]

    def execute(self, name, args):
        return ToolResult(ok=False, output=NOT_ENABLED)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_tool_computer.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/tools/computer.py tests/test_tool_computer.py pyproject.toml
git commit -m "feat: computer tool placeholder for future C-level control"
```

---

### Task 7: 意图分类器

**Files:**
- Create: `src/assistant/core/intent.py`
- Test: `tests/test_intent.py`

**Interfaces:**
- Consumes: `Provider`
- Produces:
  - `Intent(Enum)`：`CHAT = "chat"`、`TASK = "task"`
  - `IntentClassifier(provider: Provider, model: Callable[[], str])`：`classify(text: str) -> Intent` —— 用短提示要求模型只回答 CHAT/TASK；解析失败（含空回复/异常）一律归 CHAT

- [ ] **Step 1: 写失败测试**

`tests/test_intent.py`:
```python
from assistant.core.intent import Intent, IntentClassifier
from assistant.providers.base import ChatMessage, Completion


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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_intent.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/core/intent.py`:
```python
from enum import Enum
from typing import Callable

from assistant.providers.base import ChatMessage, Provider


class Intent(Enum):
    CHAT = "chat"
    TASK = "task"


_SYSTEM = (
    "判断用户输入属于哪一类：\n"
    "- TASK：要求你操作电脑完成实际工作（操作文件、启动/关闭程序、"
    "执行命令、搜索或抓取网页、整理资料等）\n"
    "- CHAT：普通聊天、情感交流、问答、咨询、闲聊\n"
    "只回答一个词：TASK 或 CHAT。"
)


class IntentClassifier:
    def __init__(self, provider: Provider, model: Callable[[], str]):
        self.provider = provider
        self.model = model

    def classify(self, text: str) -> Intent:
        try:
            result = self.provider.chat(
                [ChatMessage("system", _SYSTEM),
                 ChatMessage("user", text)],
                model=self.model())
            answer = result.content.strip().upper()
            return Intent.TASK if answer == "TASK" else Intent.CHAT
        except Exception:
            return Intent.CHAT
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_intent.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/core/intent.py tests/test_intent.py
git commit -m "feat: intent classifier routing chat vs task"
```

---

### Task 8: 安全策略

**Files:**
- Create: `src/assistant/agent/__init__.py`
- Create: `src/assistant/agent/safety.py`
- Test: `tests/test_safety.py`

**Interfaces:**
- Consumes: `RiskLevel`
- Produces:
  - `ConfirmationRequest(tool_name: str, args: dict, session_id: str | None)`
  - `ConfirmCallback` Protocol：`__call__(request: ConfirmationRequest) -> bool`
  - `Policy(autopilot: bool = False)`：`needs_confirmation(risk: RiskLevel) -> bool`（HIGH 且非自动驾驶才需要）、`set_autopilot(on: bool)`

- [ ] **Step 1: 写失败测试**

`tests/test_safety.py`:
```python
from assistant.agent.safety import Policy
from assistant.tools.base import RiskLevel


def test_low_risk_never_needs_confirmation():
    assert not Policy().needs_confirmation(RiskLevel.LOW)
    assert not Policy(autopilot=True).needs_confirmation(RiskLevel.LOW)


def test_high_risk_needs_confirmation_by_default():
    assert Policy().needs_confirmation(RiskLevel.HIGH)


def test_high_risk_passes_in_autopilot():
    assert not Policy(autopilot=True).needs_confirmation(RiskLevel.HIGH)


def test_set_autopilot():
    p = Policy()
    p.set_autopilot(True)
    assert not p.needs_confirmation(RiskLevel.HIGH)
    p.set_autopilot(False)
    assert p.needs_confirmation(RiskLevel.HIGH)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_safety.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/agent/safety.py`:
```python
from dataclasses import dataclass
from typing import Protocol

from assistant.tools.base import RiskLevel


@dataclass
class ConfirmationRequest:
    tool_name: str
    args: dict
    session_id: str | None = None


class ConfirmCallback(Protocol):
    def __call__(self, request: ConfirmationRequest) -> bool: ...


class Policy:
    def __init__(self, autopilot: bool = False):
        self._autopilot = autopilot

    def set_autopilot(self, on: bool) -> None:
        self._autopilot = on

    def needs_confirmation(self, risk: RiskLevel) -> bool:
        return (not self._autopilot) and risk is RiskLevel.HIGH
```

`src/assistant/agent/__init__.py`（空文件）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_safety.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/agent tests/test_safety.py
git commit -m "feat: safety policy with autopilot mode"
```

---

### Task 9: Agent 多步任务引擎

**Files:**
- Create: `src/assistant/agent/engine.py`
- Create: `src/assistant/agent/recorder.py`
- Test: `tests/test_agent_engine.py`

**Interfaces:**
- Consumes: `Provider`、`ToolRegistry`、`Policy`、`ConfirmCallback`、`Database`
- Produces:
  - `AgentEvent` dataclass：`type: str`（plan/step_start/step_end/done/failed）、`payload: dict`
  - `TaskReport(success: bool, summary: str, steps: list[dict])`
  - `TaskRecorder(db: Database)`：`record(session_id, task_id, step_no, tool, args, result, status)`（写 `task_steps` 表）
  - `AgentEngine(provider, tools: ToolRegistry, model, policy: Policy, on_event=None, confirm: ConfirmCallback | None = None, stop: Callable[[], bool] | None = None, recorder: TaskRecorder | None = None)`：
    - `run_task(goal: str, session_id: str | None = None) -> TaskReport`
    - 常量 `MAX_STEPS = 12`、`MAX_CONSECUTIVE_FAILURES = 3`
    - 流程：① 无工具调用出计划（事件 plan）→ ② 带工具循环（step_start/step_end 事件，工具结果以 tool 角色消息回喂，失败让模型自纠）→ ③ 模型输出总结文本即结束（事件 done）；连续失败达上限或步数用尽 → failed；每轮迭代前检查 stop()，被停止返回 failed + "已手动停止" 说明

- [ ] **Step 1: 写失败测试（脚本化 FakeProvider）**

`tests/test_agent_engine.py`:
```python
from assistant.agent.engine import AgentEngine, TaskReport
from assistant.agent.safety import Policy
from assistant.providers.base import ChatMessage, Completion, ToolCall
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

    def chat(self, messages, model, tools=None, on_delta=None):
        self.messages_log.append(list(messages))
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(step, tuple):  # ("tool", name, args)
            return Completion(tool_calls=[ToolCall(id="c", name=step[1],
                                                   arguments=step[2])])
        return Completion(content=step)


def make_engine(script, **kw):
    provider = ScriptedProvider(script)
    reg = ToolRegistry()
    reg.register(EchoTool())
    engine = AgentEngine(provider, reg, model=lambda: "m", policy=Policy(),
                         **kw)
    return provider, reg, engine


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
    from assistant.agent.safety import Policy as P
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
                         policy=P(autopilot=True),
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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_agent_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 recorder**

`src/assistant/agent/recorder.py`:
```python
import json

from assistant.core.sessions import now_iso
from assistant.storage.db import Database


class TaskRecorder:
    def __init__(self, db: Database):
        self.db = db

    def record(self, session_id, task_id, step_no, tool, args, result,
               status) -> None:
        self.db.execute(
            "INSERT INTO task_steps (session_id, task_id, step_no, tool, "
            "args, result, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, task_id, step_no, tool,
             json.dumps(args, ensure_ascii=False),
             json.dumps(result, ensure_ascii=False), status, now_iso()))
```

- [ ] **Step 4: 实现引擎**

`src/assistant/agent/engine.py`:
```python
import json
import uuid
from dataclasses import dataclass, field
from typing import Callable

from assistant.agent.recorder import TaskRecorder
from assistant.agent.safety import ConfirmCallback, ConfirmationRequest, Policy
from assistant.providers.base import ChatMessage, Completion, Provider, ToolCall
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
    ):
        self.provider = provider
        self.tools = tools
        self.model = model
        self.policy = policy
        self.on_event = on_event or (lambda e: None)
        self.confirm = confirm or (lambda r: True)
        self.stop = stop or (lambda: False)
        self.recorder = recorder

    def run_task(self, goal: str, session_id: str | None = None) -> TaskReport:
        task_id = uuid.uuid4().hex
        messages = [ChatMessage("system", EXECUTOR_SYSTEM),
                    ChatMessage("user", goal)]
        steps: list[dict] = []
        step_no = 0
        consecutive_failures = 0

        # ① 计划阶段（不带工具）
        plan = self.provider.chat(messages, model=self.model())
        plan_text = plan.content.strip()
        self.on_event(AgentEvent("plan", {"goal": goal, "plan": plan_text}))
        if plan_text:
            messages.append(ChatMessage("assistant", plan_text))

        # ② 执行循环
        tool_specs = self.tools.list_specs()
        for _ in range(self.MAX_STEPS):
            if self.stop():
                return self._finish(False, "任务已被用户手动停止。",
                                    task_id, session_id, steps, step_no)
            completion = self.provider.chat(
                messages, model=self.model(), tools=tool_specs)
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
                        False, "连续多次失败，任务中止。请检查后重试或调整要求。",
                        task_id, session_id, steps, step_no)
            else:
                summary = completion.content.strip()
                if summary:
                    messages.append(ChatMessage("assistant", summary))
                self.on_event(AgentEvent("done", {"summary": summary}))
                return TaskReport(success=True, summary=summary,
                                  steps=steps)
        return self._finish(
            False, "达到最大执行步数，任务中止。", task_id, session_id,
            steps, step_no)

    def _finish(self, success, summary, task_id, session_id, steps, step_no):
        self.on_event(AgentEvent("failed", {"summary": summary}))
        return TaskReport(success=success, summary=summary, steps=steps)

    def _persist(self, task_id, session_id, step_no, record):
        if self.recorder and session_id:
            self.recorder.record(
                session_id=session_id, task_id=task_id, step_no=step_no,
                tool=record.get("tool"), args=record.get("args", {}),
                result=record.get("output", ""), status=record["status"])
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_agent_engine.py -v`
Expected: 7 PASS

- [ ] **Step 6: Commit**

```bash
git add src/assistant/agent tests/test_agent_engine.py
git commit -m "feat: multi-step agent engine with plan, retry and safety"
```

---

### Task 10: 任务路由器（双线分派）

**Files:**
- Create: `src/assistant/core/tasks.py`
- Test: `tests/test_tasks.py`

**Interfaces:**
- Consumes: `ChatService`、`IntentClassifier`、`AgentEngine`、`SessionManager`
- Produces: `TaskRouter(chat: ChatService, classifier: IntentClassifier, engine_factory: Callable[[], AgentEngine], sessions: SessionManager)`：
  - `route(session_id: str, text: str, on_delta: Callable[[str], None], on_event: Callable[[AgentEvent], None]) -> str | TaskReport`
    - CHAT → `chat.stream_reply(...)`，返回回复文本
    - TASK → 持久化用户消息与任务汇报（assistant 角色），返回 `TaskReport`

- [ ] **Step 1: 写失败测试**

`tests/test_tasks.py`:
```python
from assistant.agent.engine import AgentEvent, TaskReport
from assistant.core.intent import Intent
from assistant.core.sessions import SessionManager
from assistant.core.tasks import TaskRouter
from assistant.storage.db import Database


class FakeClassifier:
    def __init__(self, intent):
        self.intent = intent

    def classify(self, text):
        return self.intent


class FakeChat:
    def __init__(self):
        self.called_with = None

    def stream_reply(self, session_id, text, on_delta):
        self.called_with = (session_id, text)
        on_delta("回复")
        return "回复内容"


def make_router(intent):
    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    chat = FakeChat()
    return db, sessions, TaskRouter(
        chat, FakeClassifier(intent), lambda: None, sessions)


def test_chat_route_goes_to_chat_service():
    _, sessions, router = make_router(Intent.CHAT)
    sid = sessions.create()
    result = router.route(sid, "你好", on_delta=lambda t: None,
                          on_event=lambda e: None)
    assert result == "回复内容"
    assert [m.role for m in sessions.history(sid)] == ["user", "assistant"]


def test_task_route_runs_engine_and_persists():
    _, sessions, router = make_router(Intent.TASK)

    class FakeEngine:
        def run_task(self, goal, session_id=None):
            return TaskReport(success=True, summary="搞定了", steps=[])

    router.engine_factory = lambda: FakeEngine()
    sid = sessions.create()
    events = []
    report = router.route(sid, "整理文件", on_delta=lambda t: None,
                          on_event=events.append)
    assert report.success is True
    history = sessions.history(sid)
    assert history[0].content == "整理文件"
    assert "搞定了" in history[1].content
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_tasks.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/core/tasks.py`:
```python
from typing import Callable

from assistant.agent.engine import AgentEngine, AgentEvent, TaskReport
from assistant.core.chat import ChatService
from assistant.core.intent import Intent, IntentClassifier
from assistant.core.sessions import SessionManager


class TaskRouter:
    def __init__(self, chat: ChatService, classifier: IntentClassifier,
                 engine_factory: Callable[[], AgentEngine],
                 sessions: SessionManager):
        self.chat = chat
        self.classifier = classifier
        self.engine_factory = engine_factory
        self.sessions = sessions

    def route(self, session_id: str, text: str,
              on_delta: Callable[[str], None],
              on_event: Callable[[AgentEvent], None]
              ) -> str | TaskReport:
        intent = self.classifier.classify(text)
        if intent is Intent.CHAT:
            return self.chat.stream_reply(session_id, text, on_delta)
        self.sessions.add_message(session_id, "user", text)
        report = self.engine_factory().run_task(text, session_id=session_id)
        if report.summary:
            self.sessions.add_message(session_id, "assistant", report.summary)
        return report
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_tasks.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/core/tasks.py tests/test_tasks.py
git commit -m "feat: task router dispatching chat vs task lines"
```

---

### Task 11: 任务线 UI 集成（活动卡片 + 确认 + 停止）

**Files:**
- Modify: `src/assistant/ui/chat_view.py`（追加任务事件渲染方法）
- Modify: `src/assistant/ui/main_window.py`（路由 + 确认卡片 + 停止按钮）
- Modify: `src/assistant/main.py`（装配 tools/engine/router/policy）
- Test: `tests/test_ui_smoke.py`（追加）

**Interfaces:**
- Consumes: `TaskRouter`、`AgentEngine`、`AgentEvent`、`Policy`、`ToolRegistry`、`ToolResult`、`ConfirmationRequest`
- Produces:
  - `ChatView` 追加：`on_task_event(event: AgentEvent)` —— 以 Markdown 追加计划（📋）、步骤开始（▶ 第 N 步：工具名）、步骤结束（✓/✗/🚫 拒绝）、完成（✅ 总结）、失败（❌ 原因）
  - `MainWindow` 追加：`stop_requested()`（点停止按钮 → 置停止标志）、确认卡片（QDialog 模态：显示工具名 + 参数，允许/拒绝）；发送流程改为 `TaskRouter.route`，任务线不流式但渲染事件
  - `main()` 装配：注册 5 个工具（Files/Apps/Shell/Browser/Computer）、Policy（cfg.autopilot_default）、TaskRecorder(db)、TaskRouter

- [ ] **Step 1: 追加冒烟测试**

`tests/test_ui_smoke.py` 追加:
```python
def test_chat_view_task_events(qapp):
    from assistant.agent.engine import AgentEvent
    from assistant.ui.chat_view import ChatView
    view = ChatView()
    view.on_task_event(AgentEvent("plan", {"plan": "计划内容"}))
    view.on_task_event(AgentEvent("step_start",
                                  {"step": 1, "tool": "echo"}))
    view.on_task_event(AgentEvent("step_end",
                                  {"step": 1, "tool": "echo",
                                   "status": "ok"}))
    view.on_task_event(AgentEvent("done", {"summary": "完成"}))
    text = view.toPlainText()
    assert "计划内容" in text
    assert "echo" in text
    assert "完成" in text
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_ui_smoke.py -v`
Expected: FAIL（on_task_event 不存在）

- [ ] **Step 3: 修改 chat_view.py**

在 `ChatView` 中追加:
```python
    def on_task_event(self, event) -> None:
        etype, payload = event.type, event.payload
        if etype == "plan":
            self._buffer += f"\n\n📋 **任务计划**\n\n{payload.get('plan', '')}\n"
        elif etype == "step_start":
            self._buffer += (f"\n▶ **第 {payload['step']} 步**："
                             f"`{payload['tool']}`\n")
        elif etype == "step_end":
            icon = {"ok": "✅", "failed": "❌", "declined": "🚫"}.get(
                payload.get("status"), "•")
            self._buffer += f"{icon} 第 {payload['step']} 步完成\n"
        elif etype == "done":
            self._buffer += f"\n\n---\n\n✅ {payload.get('summary', '')}\n"
        elif etype == "failed":
            self._buffer += f"\n\n❌ {payload.get('summary', '')}\n"
        self._flush()
```

- [ ] **Step 4: 修改 main_window.py**

`_send` 改为（保留原有 import，新增 `QDialog` 相关与 `AgentEngine` 依赖）:
```python
    def _send(self):
        if not self.current_session_id:
            self._create_session()
        text = self.input_box.toPlainText().strip()
        if not text:
            return
        self.input_box.clear()
        self.chat_view.append_user(text)
        session_id = self.current_session_id
        self.send_button.setEnabled(False)
        self.stop_button.setVisible(True)
        self._stop_flag.clear()
        self.router = self.router_factory()   # 每任务新实例，见 main.py

        def worker():
            try:
                result = self.router.route(
                    session_id, text,
                    on_delta=lambda t: self.bus.publish(
                        "chat.delta", session_id=session_id, text=t),
                    on_event=lambda ev: self.bus.publish(
                        "task.event", session_id=session_id, event=ev))
                if hasattr(result, "summary"):   # TaskReport
                    self.bus.publish("chat.done", session_id=session_id,
                                     reply=result.summary)
                else:
                    self.bus.publish("chat.done", session_id=session_id,
                                     reply=result)
            except Exception as exc:
                self.bus.publish("chat.error", session_id=session_id,
                                 message=str(exc))

        threading.Thread(target=worker, daemon=True).start()
```

`_BusBridge` 追加信号 `task_event = Signal(str, object)`；`__init__` 追加订阅:
```python
        self.bridge.task_event.connect(self._on_task_event)
        self.bus.subscribe("task.event", lambda **kw: self.bridge.task_event.emit(
            kw["session_id"], kw["event"]))
```

追加方法:
```python
    def _on_task_event(self, session_id, event):
        if session_id == self.current_session_id:
            self.chat_view.on_task_event(event)

    def stop_requested(self):
        self._stop_flag.set()
```

`__init__` 中 input_row 加停止按钮:
```python
        self.stop_button = QPushButton("停止")
        self.stop_button.setVisible(False)
        self.stop_button.clicked.connect(self.stop_requested)
        input_row.addWidget(self.stop_button)
```
并初始化 `self._stop_flag = threading.Event()`。

确认回调在 main.py 装配（见 Step 6）。

- [ ] **Step 5: 实现确认对话框**

新建 `src/assistant/ui/confirm_dialog.py`:
```python
import json

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QVBoxLayout,
)

from assistant.agent.safety import ConfirmationRequest


class ConfirmDialog(QDialog):
    """高风控操作确认。返回 True=允许。"""

    def __init__(self, request: ConfirmationRequest, parent=None):
        super().__init__(parent)
        self.setWindowTitle("操作确认")
        args = json.dumps(request.args, ensure_ascii=False, indent=2)
        label = QLabel(
            f"<b>即将执行高风控操作：{request.tool_name}</b><br><br>"
            f"参数：<pre>{args}</pre>")
        label.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("允许")
        buttons.button(QDialogButtonBox.Cancel).setText("拒绝")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(buttons)
```

- [ ] **Step 6: 修改 main.py 装配（完整替换 main()）**

`src/assistant/main.py` 完整内容:
```python
import sys

from PySide6.QtWidgets import QApplication

from assistant.agent.engine import AgentEngine
from assistant.agent.recorder import TaskRecorder
from assistant.agent.safety import Policy
from assistant.core.chat import ChatService
from assistant.core.intent import IntentClassifier
from assistant.core.sessions import SessionManager
from assistant.core.tasks import TaskRouter
from assistant.providers.registry import ProviderRegistry
from assistant.storage.config import ConfigManager
from assistant.storage.db import Database
from assistant.storage.paths import data_dir
from assistant.storage.secrets import SecretsStore, WindowsDpapiBackend
from assistant.tools.apps import AppsTool
from assistant.tools.browser import BrowserTool
from assistant.tools.computer import ComputerTool
from assistant.tools.files import FilesTool
from assistant.tools.registry import ToolRegistry
from assistant.tools.shell import ShellTool
from assistant.ui.confirm_dialog import ConfirmDialog
from assistant.ui.main_window import MainWindow


def _make_secrets() -> SecretsStore:
    import os
    if os.name == "nt":
        backend = WindowsDpapiBackend()
    else:
        class _PlainBackend:
            def encrypt(self, data: bytes) -> bytes:
                return data

            def decrypt(self, data: bytes) -> bytes:
                return data
        backend = _PlainBackend()
    return SecretsStore(data_dir() / "secrets.dat", backend)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("assistant")

    cfg = ConfigManager(data_dir() / "config.json").load()
    db = Database(data_dir() / "assistant.db")
    db.migrate()
    secrets = _make_secrets()

    registry = ProviderRegistry()
    provider = registry.create(
        cfg.models.provider, cfg.models.base_url,
        secrets.get(cfg.models.provider) or "")

    sessions = SessionManager(db)
    chat = ChatService(sessions, provider, model=lambda: cfg.models.model)

    tool_registry = ToolRegistry()
    for tool in (FilesTool(), AppsTool(), ShellTool(), BrowserTool(),
                 ComputerTool()):
        tool_registry.register(tool)

    policy = Policy(autopilot=cfg.autopilot_default)
    classifier = IntentClassifier(provider, model=lambda: cfg.models.model)
    recorder = TaskRecorder(db)

    # 闭包晚绑定：make_engine 每次任务被调用时 window 已存在
    def make_engine() -> AgentEngine:
        return AgentEngine(
            provider, tool_registry, model=lambda: cfg.models.task_model,
            policy=policy, recorder=recorder,
            confirm=lambda req: ConfirmDialog(req, window).exec() == 1,
            stop=lambda: window._stop_flag.is_set())

    router = TaskRouter(chat, classifier, make_engine, sessions)
    window = MainWindow(sessions, chat, cfg, secrets, router)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

同时 `MainWindow.__init__` 签名改为 `(self, sessions, chat, cfg, secrets, router)`，函数体追加 `self.router = router`；`_send` 中删除 `self.router = self.router_factory()` 一行，直接使用 `self.router.route(...)`。

- [ ] **Step 7: 跑冒烟测试确认通过**

`tests/test_ui_smoke.py` 中 `test_main_window_constructs` 同步更新为:
```python
def test_main_window_constructs(qapp):
    from assistant.core.chat import ChatService
    from assistant.core.sessions import SessionManager
    from assistant.storage.db import Database
    from assistant.ui.main_window import MainWindow

    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    chat = ChatService(sessions, provider=None, model=lambda: "deepseek-chat")
    win = MainWindow(sessions, chat, None, None, router=None)
    assert win.windowTitle() == "assistant"
```

Run: `.venv/bin/python -m pytest tests/test_ui_smoke.py -v`
Expected: 3 PASS（原 2 + 新 1）

- [ ] **Step 8: 手工验证**

Run: `.venv/bin/python -m assistant`
Expected（按序）：
1. 聊天类消息（"你好"）→ 正常流式回复（回归 Plan 1）
2. 任务类消息（"在桌面建一个名为 test.txt 的文件，写入 hello"）→ 显示 📋 计划、▶ 步骤、✅/❌ 状态、✅ 总结；文件确实被创建
3. 发"删除桌面的 test.txt"（非自动驾驶）→ 弹出确认框，点拒绝 → 🚫 步骤显示拒绝，文件仍在
4. 再发一次并点允许 → 文件被删除
5. 发一个会失败的任务（"读取不存在的文件 X:\nope.txt"）→ 引擎重试后如实报告失败
6. 任务执行中点"停止" → 任务中止，界面显示"已手动停止"
7. 设置里勾选自动驾驶 → 重启后删文件不再弹确认，但聊天流中明示了即将执行

- [ ] **Step 9: Commit**

```bash
git add src/assistant/ui src/assistant/main.py tests/test_ui_smoke.py
git commit -m "feat: task-line UI with activity cards, confirmation and stop"
```

---

## 计划完成标准

- [ ] `pytest` 全绿（Plan 1 30 个 + 本计划 46 个 = 76 个测试）
- [ ] 手工验证清单全部通过
- [ ] 每条 task 已 commit
- [ ] 工具协议、AgentEngine、TaskRouter 接口冻结，供 Plan 3 使用
