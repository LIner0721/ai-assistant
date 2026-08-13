# Assistant 平台底座 + 聊天应用 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 assistant 项目骨架（Python + PySide6），实现存储/配置/密钥/模型适配器/会话/聊天服务，交付一个能与 DeepSeek 流式聊天的桌面应用。

**Architecture:** 单体 Python 应用，严格分层：`ui` 不知道模型和工具的存在；`core` 提供会话/聊天/事件总线；`providers` 是模型供应商适配层（OpenAI 兼容协议）；`storage` 管 SQLite、配置、密钥。UI 线程与 worker 线程通过 EventBus + Qt 信号解耦。

**Tech Stack:** Python 3.12、PySide6、httpx、markdown + pygments（渲染）、SQLite（stdlib）、pytest。

**Spec:** `docs/superpowers/specs/2026-08-13-windows-ai-assistant-design.md`

## Global Constraints

- Python `>=3.12,<3.14`；目标平台 Windows 10/11 64 位（开发机为 Linux，所有代码必须跨平台，Windows 专属库只放 `windows` extra 并延迟导入）
- 包名/模块前缀 `assistant`，src 布局（`src/assistant/`），可执行名 `assistant.exe`（打包时定）
- 默认模型供应商 DeepSeek：base_url `https://api.deepseek.com/v1`，默认模型 `deepseek-chat`
- 存储引擎 SQLite，无 ORM，手写 SQL；schema 用 `schema_version` 表 + 顺序迁移脚本
- API key 禁止明文落盘；Windows 上 DPAPI 加密（`secrets.dat`）
- 全部核心逻辑 TDD（pytest），UI 手工验证
- 线程模型：Qt 主线程只做 UI；模型调用在 worker 线程；跨线程通信只用 EventBus + Qt 信号
- 每条任务完成必须 git commit

---

## 文件结构总览（本计划创建）

```
pyproject.toml
src/assistant/
├── __init__.py
├── main.py              # 入口：装配所有组件，启动 QApplication
├── storage/
│   ├── __init__.py
│   ├── paths.py         # 数据目录定位（Windows: %APPDATA%\assistant）
│   ├── db.py            # Database + 迁移
│   ├── config.py        # AppConfig / ConfigManager
│   └── secrets.py       # CryptoBackend / SecretsStore
├── providers/
│   ├── __init__.py
│   ├── base.py          # ChatMessage / Completion / Provider 接口
│   ├── openai_compat.py # OpenAI 兼容适配器（DeepSeek 默认）
│   └── registry.py      # ProviderRegistry
├── core/
│   ├── __init__.py
│   ├── eventbus.py      # 线程安全事件总线
│   ├── sessions.py      # SessionManager
│   └── chat.py          # ChatService（人设 + 流式 + 持久化）
└── ui/
    ├── __init__.py
    ├── render.py        # markdown → HTML（代码高亮）
    ├── chat_view.py     # 对话区（流式渲染）
    ├── session_list.py  # 会话列表
    ├── settings_dialog.py
    └── main_window.py   # 主窗口
tests/
├── test_db.py
├── test_config.py
├── test_secrets.py
├── test_providers.py
├── test_eventbus.py
├── test_sessions.py
└── test_chat.py
```

---

### Task 1: 项目脚手架 + SQLite 存储层

**Files:**
- Create: `pyproject.toml`
- Create: `src/assistant/__init__.py`
- Create: `src/assistant/storage/__init__.py`
- Create: `src/assistant/storage/paths.py`
- Create: `src/assistant/storage/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: 无（第一个任务）
- Produces:
  - `assistant.storage.paths.data_dir() -> Path` —— Windows 返回 `%APPDATA%/assistant`，其他系统返回 `~/.assistant`
  - `assistant.storage.db.Database(path: str | Path)`，方法：
    - `migrate() -> None` —— 顺序执行未应用的迁移
    - `execute(sql: str, params: tuple = ()) -> int` —— 返回 lastrowid
    - `query(sql: str, params: tuple = ()) -> list[sqlite3.Row]`
    - `query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None`
    - `commit() -> None`、`close() -> None`
    - `schema_version() -> int`
  - 迁移 v1 建表：`sessions`、`messages`、`task_steps`、`memories`、`settings`（schema 见下）

- [ ] **Step 1: 写脚手架文件**

`pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "assistant"
version = "0.1.0"
description = "Personal Windows AI assistant"
requires-python = ">=3.12,<3.14"
dependencies = [
    "PySide6>=6.6",
    "httpx>=0.27",
    "markdown>=3.5",
    "pygments>=2.17",
]

[project.optional-dependencies]
windows = ["pywin32>=306"]
dev = ["pytest>=8.0"]

[project.scripts]
assistant = "assistant.main:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`src/assistant/__init__.py`:
```python
__version__ = "0.1.0"
```

`src/assistant/storage/__init__.py`（空文件）。

`src/assistant/storage/paths.py`:
```python
import os
from pathlib import Path

APP_NAME = "assistant"


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path.home() / ".assistant"
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [ ] **Step 2: 写失败测试**

`tests/test_db.py`:
```python
from assistant.storage.db import Database


def test_migrate_creates_tables():
    db = Database(":memory:")
    db.migrate()
    tables = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"sessions", "messages", "task_steps", "memories",
            "settings", "schema_version"} <= tables
    assert db.schema_version() == 1


def test_migrate_is_idempotent():
    db = Database(":memory:")
    db.migrate()
    db.migrate()
    assert db.schema_version() == 1


def test_execute_and_query():
    db = Database(":memory:")
    db.migrate()
    sid = "s1"
    db.execute(
        "INSERT INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, ?, '2026-01-01', '2026-01-01')", (sid, "测试"))
    row = db.query_one("SELECT title FROM sessions WHERE id = ?", (sid,))
    assert row["title"] == "测试"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/python -m pytest tests/test_db.py -v`（Windows 下用 `.venv\Scripts\`）
Expected: FAIL（`No module named 'assistant.storage'`）

- [ ] **Step 4: 实现 Database 与迁移**

`src/assistant/storage/db.py`:
```python
import sqlite3
from pathlib import Path

MIGRATIONS: list[str] = [
    # v1: 初始 schema
    """
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE task_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        step_no INTEGER NOT NULL,
        tool TEXT,
        args TEXT,
        result TEXT,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        content TEXT NOT NULL,
        tags TEXT,
        importance REAL NOT NULL DEFAULT 0.5,
        created_at TEXT NOT NULL,
        last_accessed_at TEXT,
        access_count INTEGER NOT NULL DEFAULT 0,
        source_session TEXT
    );
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]


class Database:
    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def migrate(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        current = self.schema_version()
        for i, sql in enumerate(MIGRATIONS, start=1):
            if i <= current:
                continue
            self._conn.executescript(sql)
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (i,))
            self._conn.commit()

    def schema_version(self) -> int:
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        return int(row[0]) if row else 0

    def execute(self, sql: str, params: tuple = ()) -> int:
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur.lastrowid or 0

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self._conn.execute(sql, params))

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src tests
git commit -m "feat: project scaffold and sqlite storage layer"
```

---

### Task 2: 配置管理

**Files:**
- Create: `src/assistant/storage/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `assistant.storage.paths.data_dir()`
- Produces:
  - `ModelConfig` dataclass：`provider: str = "deepseek"`、`model: str = "deepseek-chat"`、`task_model: str = "deepseek-chat"`、`base_url: str = "https://api.deepseek.com/v1"`
  - `AppConfig` dataclass：`models: ModelConfig`、`hotkey: str = "<ctrl>+<alt>+<space>"`、`autopilot_default: bool = False`、`autostart: bool = False`
  - `ConfigManager(path: Path)`：`load() -> AppConfig`（缺失字段用默认值，JSON 损坏时返回全默认）、`save(config: AppConfig) -> None`

- [ ] **Step 1: 写失败测试**

`tests/test_config.py`:
```python
from assistant.storage.config import AppConfig, ConfigManager


def test_load_missing_file_returns_defaults(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cfg = cm.load()
    assert cfg.models.model == "deepseek-chat"
    assert cfg.models.base_url == "https://api.deepseek.com/v1"
    assert cfg.hotkey == "<ctrl>+<alt>+<space>"
    assert cfg.autopilot_default is False


def test_save_and_load_roundtrip(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cfg = AppConfig()
    cfg.models.model = "qwen-plus"
    cfg.autopilot_default = True
    cm.save(cfg)
    loaded = cm.load()
    assert loaded.models.model == "qwen-plus"
    assert loaded.autopilot_default is True


def test_load_partial_json_fills_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"hotkey": "<ctrl>+<shift>+a"}', encoding="utf-8")
    cfg = ConfigManager(p).load()
    assert cfg.hotkey == "<ctrl>+<shift>+a"
    assert cfg.models.model == "deepseek-chat"


def test_load_corrupt_json_returns_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("not json{{", encoding="utf-8")
    cfg = ConfigManager(p).load()
    assert cfg.models.model == "deepseek-chat"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`src/assistant/storage/config.py`:
```python
import json
from dataclasses import dataclass, asdict, field, fields
from pathlib import Path


@dataclass
class ModelConfig:
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    task_model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"


@dataclass
class AppConfig:
    models: ModelConfig = field(default_factory=ModelConfig)
    hotkey: str = "<ctrl>+<alt>+<space>"
    autopilot_default: bool = False
    autostart: bool = False


def _fill(dc, data: dict):
    for f in fields(dc):
        if f.name in data:
            value = data[f.name]
            if isinstance(getattr(dc, f.name), ModelConfig) and isinstance(value, dict):
                value = _fill(ModelConfig(), value)
            setattr(dc, f.name, value)
    return dc


class ConfigManager:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> AppConfig:
        cfg = AppConfig()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return cfg
        if isinstance(data, dict):
            _fill(cfg, data)
        return cfg

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2),
            encoding="utf-8")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/storage/config.py tests/test_config.py
git commit -m "feat: config management with defaults and tolerant loading"
```

---

### Task 3: 密钥安全存储（DPAPI）

**Files:**
- Create: `src/assistant/storage/secrets.py`
- Test: `tests/test_secrets.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `CryptoBackend` Protocol：`encrypt(data: bytes) -> bytes`、`decrypt(data: bytes) -> bytes`
  - `WindowsDpapiBackend`：实现 CryptoBackend，内部用 `win32crypt.CryptProtectData/CryptUnprotectData`（延迟导入，仅 Windows 可用）
  - `SecretsStore(path: Path, backend: CryptoBackend)`：`set(name, value)`、`get(name) -> str | None`、`delete(name)`。文件格式：`{"<name>": "<base64密文>"}`

- [ ] **Step 1: 写失败测试**

`tests/test_secrets.py`:
```python
import base64
from assistant.storage.secrets import SecretsStore


class FakeBackend:
    def encrypt(self, data: bytes) -> bytes:
        return b"enc:" + data

    def decrypt(self, data: bytes) -> bytes:
        assert data.startswith(b"enc:")
        return data[4:]


def test_set_get_roundtrip(tmp_path):
    store = SecretsStore(tmp_path / "secrets.dat", FakeBackend())
    store.set("deepseek", "sk-test-123")
    assert store.get("deepseek") == "sk-test-123"


def test_get_missing_returns_none(tmp_path):
    store = SecretsStore(tmp_path / "secrets.dat", FakeBackend())
    assert store.get("nope") is None


def test_key_not_stored_in_plaintext(tmp_path):
    store = SecretsStore(tmp_path / "secrets.dat", FakeBackend())
    store.set("deepseek", "sk-secret-value")
    raw = (tmp_path / "secrets.dat").read_text(encoding="utf-8")
    assert "sk-secret-value" not in raw
    # 密文确实是 base64(enc:...) 形式
    import json
    payload = json.loads(raw)
    assert base64.b64decode(payload["deepseek"]) == b"enc:sk-secret-value"


def test_delete(tmp_path):
    store = SecretsStore(tmp_path / "secrets.dat", FakeBackend())
    store.set("a", "1")
    store.delete("a")
    assert store.get("a") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_secrets.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/storage/secrets.py`:
```python
import base64
import json
from pathlib import Path
from typing import Protocol


class CryptoBackend(Protocol):
    def encrypt(self, data: bytes) -> bytes: ...
    def decrypt(self, data: bytes) -> bytes: ...


class WindowsDpapiBackend:
    """Windows DPAPI 加密。只在 Windows 上可实例化。"""

    def __init__(self) -> None:
        import win32crypt  # noqa: F401  # 延迟导入：pywin32 仅在 Windows extra 中
        self._win32crypt = win32crypt

    def encrypt(self, data: bytes) -> bytes:
        return self._win32crypt.CryptProtectData(data, None, None, None, None, 0)

    def decrypt(self, data: bytes) -> bytes:
        return self._win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]


class SecretsStore:
    def __init__(self, path: Path, backend: CryptoBackend):
        self.path = path
        self.backend = backend

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def set(self, name: str, value: str) -> None:
        data = self._read()
        data[name] = base64.b64encode(
            self.backend.encrypt(value.encode("utf-8"))).decode("ascii")
        self._write(data)

    def get(self, name: str) -> str | None:
        data = self._read()
        encoded = data.get(name)
        if encoded is None:
            return None
        return self.backend.decrypt(base64.b64decode(encoded)).decode("utf-8")

    def delete(self, name: str) -> None:
        data = self._read()
        if name in data:
            del data[name]
            self._write(data)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_secrets.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/storage/secrets.py tests/test_secrets.py
git commit -m "feat: secrets store with pluggable crypto backend"
```

---

### Task 4: 模型供应商适配层

**Files:**
- Create: `src/assistant/providers/__init__.py`
- Create: `src/assistant/providers/base.py`
- Create: `src/assistant/providers/openai_compat.py`
- Create: `src/assistant/providers/registry.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `ChatMessage(role: str, content: str)`，方法 `to_openai() -> dict`
  - `ToolCall(id: str, name: str, arguments: dict)`
  - `Completion(content: str, tool_calls: list[ToolCall])`
  - `Provider`（ABC）：`chat(messages: list[ChatMessage], model: str, tools: list[dict] | None = None, on_delta: Callable[[str], None] | None = None) -> Completion`
  - `OpenAICompatProvider(base_url: str, api_key: str)`：httpx 客户端；支持流式（SSE）与非流式；正确累积 tool_calls 增量
  - `ProviderRegistry`：`create(provider: str, base_url: str, api_key: str) -> Provider` —— 目前 `"deepseek"` 与默认均返回 OpenAICompatProvider，未知名字抛 `ValueError`

- [ ] **Step 1: 写失败测试（用 httpx.MockTransport）**

`tests/test_providers.py`:
```python
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


def test_registry_creates_provider_and_rejects_unknown():
    reg = ProviderRegistry()
    p = reg.create("deepseek", "https://api.deepseek.com/v1", "sk-1")
    assert isinstance(p, OpenAICompatProvider)
    import pytest
    with pytest.raises(ValueError):
        reg.create("unknown-provider", "http://x", "sk-2")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_providers.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`src/assistant/providers/__init__.py`:
```python
from assistant.providers.base import ChatMessage, Completion, Provider, ToolCall
from assistant.providers.registry import ProviderRegistry

__all__ = ["ChatMessage", "Completion", "Provider", "ToolCall", "ProviderRegistry"]
```

`src/assistant/providers/base.py`:
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ChatMessage:
    role: str
    content: str

    def to_openai(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Completion:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class Provider(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        tools: list[dict] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> Completion:
        """调用模型。on_delta 提供时走流式，每个文本增量回调一次。"""
```

`src/assistant/providers/openai_compat.py`:
```python
import json
import httpx

from assistant.providers.base import ChatMessage, Completion, Provider, ToolCall


class OpenAICompatProvider(Provider):
    """OpenAI 兼容协议适配器：DeepSeek / 通义 / Kimi 通用。"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0))

    def chat(self, messages, model, tools=None, on_delta=None) -> Completion:
        payload = {
            "model": model,
            "messages": [m.to_openai() for m in messages],
        }
        if tools:
            payload["tools"] = tools
        if on_delta is not None:
            payload["stream"] = True
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
        if on_delta is not None:
            return self._parse_stream(response, on_delta)
        return self._parse_once(response)

    def _parse_once(self, response: httpx.Response) -> Completion:
        data = response.json()
        message = data["choices"][0]["message"]
        tool_calls = [
            ToolCall(id=t["id"], name=t["function"]["name"],
                     arguments=json.loads(t["function"]["arguments"] or "{}"))
            for t in (message.get("tool_calls") or [])
        ]
        return Completion(content=message.get("content") or "", tool_calls=tool_calls)

    def _parse_stream(self, response: httpx.Response,
                      on_delta) -> Completion:
        content_parts: list[str] = []
        tool_buf: dict[int, dict] = {}
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
                on_delta(delta["content"])
            for tc in delta.get("tool_calls") or []:
                buf = tool_buf.setdefault(tc["index"], {
                    "id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    buf["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    buf["name"] = fn["name"]
                if fn.get("arguments"):
                    buf["arguments"] += fn["arguments"]
        tool_calls = [
            ToolCall(id=b["id"], name=b["name"],
                     arguments=json.loads(b["arguments"] or "{}"))
            for _, b in sorted(tool_buf.items())
        ]
        return Completion(content="".join(content_parts), tool_calls=tool_calls)
```

`src/assistant/providers/registry.py`:
```python
from assistant.providers.base import Provider
from assistant.providers.openai_compat import OpenAICompatProvider


class ProviderRegistry:
    """openai-compat 适配器覆盖全部已知供应商，未来不兼容的再加专门适配器。"""

    _OPENAI_COMPAT = {"deepseek", "qwen", "kimi", "openai", "default"}

    def create(self, provider: str, base_url: str, api_key: str) -> Provider:
        if provider in self._OPENAI_COMPAT:
            return OpenAICompatProvider(base_url, api_key)
        raise ValueError(f"unknown provider: {provider}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_providers.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/providers tests/test_providers.py
git commit -m "feat: openai-compatible provider layer with streaming"
```

---

### Task 5: 事件总线

**Files:**
- Create: `src/assistant/core/__init__.py`
- Create: `src/assistant/core/eventbus.py`
- Test: `tests/test_eventbus.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `EventBus`：`subscribe(topic: str, handler: Callable[..., None]) -> None`、`publish(topic: str, **payload) -> None`。线程安全；单个 handler 抛异常不影响其他 handler（异常打印到 stderr）

- [ ] **Step 1: 写失败测试**

`tests/test_eventbus.py`:
```python
import threading
from assistant.core.eventbus import EventBus


def test_publish_delivers_payload():
    bus = EventBus()
    got = []
    bus.subscribe("chat.delta", lambda text, **kw: got.append(text))
    bus.publish("chat.delta", text="hello")
    assert got == ["hello"]


def test_bad_handler_does_not_block_others():
    bus = EventBus()
    got = []

    def bad(**kw):
        raise RuntimeError("boom")

    bus.subscribe("t", bad)
    bus.subscribe("t", lambda **kw: got.append(1))
    bus.publish("t")
    assert got == [1]


def test_cross_thread_publish():
    bus = EventBus()
    got = []
    bus.subscribe("t", lambda v, **kw: got.append(v))
    t = threading.Thread(target=lambda: bus.publish("t", v=42))
    t.start()
    t.join()
    assert got == [42]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_eventbus.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/core/eventbus.py`:
```python
import threading
import traceback
from collections import defaultdict
from typing import Callable


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Callable) -> None:
        with self._lock:
            self._handlers[topic].append(handler)

    def publish(self, topic: str, **payload) -> None:
        with self._lock:
            handlers = list(self._handlers.get(topic, ()))
        for handler in handlers:
            try:
                handler(**payload)
            except Exception:
                traceback.print_exc()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_eventbus.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/core/eventbus.py tests/test_eventbus.py
git commit -m "feat: thread-safe event bus"
```

---

### Task 6: 会话管理

**Files:**
- Create: `src/assistant/core/sessions.py`
- Test: `tests/test_sessions.py`

**Interfaces:**
- Consumes: `Database`（`execute`/`query`/`query_one`）
- Produces:
  - `Session` dataclass：`id: str`、`title: str`、`created_at: str`、`updated_at: str`
  - `SessionManager(db: Database)`：
    - `create(title: str = "新会话") -> str` —— 返回会话 id
    - `list() -> list[Session]` —— 按 updated_at 倒序
    - `rename(session_id: str, title: str) -> None`
    - `delete(session_id: str) -> None` —— 级联删除消息
    - `add_message(session_id: str, role: str, content: str) -> None` —— 同时刷新 updated_at
    - `history(session_id: str) -> list[ChatMessage]` —— 按时间正序
    - `search(query: str) -> list[Session]` —— 标题或消息内容 LIKE 匹配
  - 时间戳工具 `now_iso() -> str`（ISO 格式，秒级）

- [ ] **Step 1: 写失败测试**

`tests/test_sessions.py`:
```python
from assistant.core.sessions import SessionManager
from assistant.storage.db import Database


def make_manager():
    db = Database(":memory:")
    db.migrate()
    return db, SessionManager(db)


def test_create_and_list():
    db, sm = make_manager()
    sid = sm.create("第一个会话")
    sessions = sm.list()
    assert len(sessions) == 1
    assert sessions[0].id == sid
    assert sessions[0].title == "第一个会话"


def test_history_order_and_rename():
    db, sm = make_manager()
    sid = sm.create()
    sm.add_message(sid, "user", "问题")
    sm.add_message(sid, "assistant", "回答")
    history = sm.history(sid)
    assert [m.content for m in history] == ["问题", "回答"]
    sm.rename(sid, "改名")
    assert sm.list()[0].title == "改名"


def test_delete_cascades_messages():
    db, sm = make_manager()
    sid = sm.create()
    sm.add_message(sid, "user", "hi")
    sm.delete(sid)
    assert sm.list() == []
    assert db.query("SELECT COUNT(*) AS n FROM messages WHERE session_id=?",
                    (sid,))[0]["n"] == 0


def test_search_finds_by_title_and_content():
    db, sm = make_manager()
    s1 = sm.create("旅游计划")
    sm.add_message(s1, "user", "推荐杭州的景点")
    s2 = sm.create("工作")
    results = sm.search("杭州")
    assert [s.id for s in results] == [s1]
    assert sm.search("旅游")[0].id == s1
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_sessions.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/core/sessions.py`:
```python
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from assistant.providers.base import ChatMessage
from assistant.storage.db import Database


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Session:
    id: str
    title: str
    created_at: str
    updated_at: str


class SessionManager:
    def __init__(self, db: Database):
        self.db = db

    def create(self, title: str = "新会话") -> str:
        sid = uuid.uuid4().hex
        ts = now_iso()
        self.db.execute(
            "INSERT INTO sessions (id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)", (sid, title, ts, ts))
        return sid

    def list(self) -> list[Session]:
        rows = self.db.query(
            "SELECT * FROM sessions ORDER BY updated_at DESC")
        return [Session(**dict(r)) for r in rows]

    def rename(self, session_id: str, title: str) -> None:
        self.db.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
            (title, now_iso(), session_id))

    def delete(self, session_id: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def add_message(self, session_id: str, role: str, content: str) -> None:
        self.db.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?)", (session_id, role, content, now_iso()))
        self.db.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?",
            (now_iso(), session_id))

    def history(self, session_id: str) -> list[ChatMessage]:
        rows = self.db.query(
            "SELECT role, content FROM messages WHERE session_id=? "
            "ORDER BY id", (session_id,))
        return [ChatMessage(role=r["role"], content=r["content"]) for r in rows]

    def search(self, query: str) -> list[Session]:
        like = f"%{query}%"
        rows = self.db.query(
            "SELECT DISTINCT s.* FROM sessions s "
            "LEFT JOIN messages m ON m.session_id = s.id "
            "WHERE s.title LIKE ? OR m.content LIKE ? "
            "ORDER BY s.updated_at DESC", (like, like))
        return [Session(**dict(r)) for r in rows]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_sessions.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/core/sessions.py tests/test_sessions.py
git commit -m "feat: session manager with history and search"
```

---

### Task 7: 聊天服务（人设 + 流式 + 持久化）

**Files:**
- Create: `src/assistant/core/chat.py`
- Test: `tests/test_chat.py`

**Interfaces:**
- Consumes: `SessionManager`、`Provider`
- Produces:
  - `SystemPromptFactory` Protocol：`__call__() -> str`
  - `DEFAULT_PERSONA: str` —— 默认人设文案（温和能干的助理，自称 assistant）
  - `ChatService(sessions: SessionManager, provider: Provider, model: Callable[[], str], system_prompt: SystemPromptFactory | None = None)`：
    - `stream_reply(session_id: str, user_text: str, on_delta: Callable[[str], None]) -> str`
      —— 持久化用户消息 → 组装 [system + 历史(最近20条) + user] → 流式调用 → 持久化回复 → 返回完整回复
    - `history_limit: int = 20` 类属性

- [ ] **Step 1: 写失败测试（用假 Provider）**

`tests/test_chat.py`:
```python
from assistant.core.chat import DEFAULT_PERSONA, ChatService
from assistant.core.sessions import SessionManager
from assistant.providers.base import ChatMessage, Completion
from assistant.storage.db import Database


class FakeProvider:
    def __init__(self):
        self.calls: list[list[ChatMessage]] = []
        self.reply = "好的，收到！"

    def chat(self, messages, model, tools=None, on_delta=None):
        self.calls.append(list(messages))
        if on_delta:
            for ch in self.reply:
                on_delta(ch)
        return Completion(content=self.reply)


def make_service():
    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    provider = FakeProvider()
    service = ChatService(sessions, provider, model=lambda: "deepseek-chat")
    return sessions, provider, service


def test_stream_reply_persists_and_streams():
    sessions, provider, service = make_service()
    sid = sessions.create()
    deltas = []
    reply = service.stream_reply(sid, "你好", on_delta=deltas.append)
    assert "".join(deltas) == "好的，收到！"
    assert reply == "好的，收到！"
    history = sessions.history(sid)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[0].content == "你好"


def test_system_prompt_uses_persona():
    sessions, provider, service = make_service()
    sid = sessions.create()
    service.stream_reply(sid, "hi", on_delta=lambda t: None)
    first = provider.calls[0][0]
    assert first.role == "system"
    assert DEFAULT_PERSONA in first.content


def test_custom_system_prompt_factory():
    sessions, provider, service = make_service()
    service.system_prompt = lambda: "你是一只猫。"
    sid = sessions.create()
    service.stream_reply(sid, "hi", on_delta=lambda t: None)
    assert provider.calls[0][0].content == "你是一只猫。"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_chat.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/core/chat.py`:
```python
from typing import Callable, Protocol

from assistant.core.sessions import SessionManager
from assistant.providers.base import ChatMessage, Provider


class SystemPromptFactory(Protocol):
    def __call__(self) -> str: ...


DEFAULT_PERSONA = (
    "你是 assistant，用户电脑上的私人 AI 助手。性格温和、可靠、偶尔幽默。"
    "回答用中文，简洁自然，像朋友一样。"
    "你有能力操作电脑（文件、应用、命令、浏览器），但只在用户要求时动手。"
)


class ChatService:
    history_limit = 20

    def __init__(
        self,
        sessions: SessionManager,
        provider: Provider,
        model: Callable[[], str],
        system_prompt: SystemPromptFactory | None = None,
    ):
        self.sessions = sessions
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt or (lambda: DEFAULT_PERSONA)

    def stream_reply(
        self,
        session_id: str,
        user_text: str,
        on_delta: Callable[[str], None],
    ) -> str:
        self.sessions.add_message(session_id, "user", user_text)
        history = self.sessions.history(session_id)
        messages = [ChatMessage("system", self.system_prompt())]
        messages += history[-self.history_limit:]
        completion = self.provider.chat(
            messages, model=self.model(), on_delta=on_delta)
        reply = completion.content
        if reply:
            self.sessions.add_message(session_id, "assistant", reply)
        return reply
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_chat.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/core/chat.py tests/test_chat.py
git commit -m "feat: chat service with persona, streaming and persistence"
```

---

### Task 8: Markdown 渲染

**Files:**
- Create: `src/assistant/ui/__init__.py`
- Create: `src/assistant/ui/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `render_markdown(text: str) -> str` —— markdown → HTML，代码块用 pygments 高亮，输出包裹 `<div class="markdown">...</div>`

- [ ] **Step 1: 写失败测试**

`tests/test_render.py`:
```python
from assistant.ui.render import render_markdown


def test_plain_text():
    html = render_markdown("你好")
    assert "你好" in html
    assert html.startswith("<div")


def test_code_block_highlighted():
    html = render_markdown("```python\nprint(1)\n```")
    # codehilite + noclasses=True 生成内联样式的高亮代码块
    assert "codehilite" in html
    assert "print" in html


def test_inline_formatting():
    html = render_markdown("**加粗** 和 `代码`")
    assert "<strong>" in html
    assert "<code>" in html
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_render.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/assistant/ui/render.py`:
```python
import markdown as md
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer


def render_markdown(text: str) -> str:
    html = md.markdown(
        text,
        extensions=["fenced_code", "codehilite", "tables"],
        extension_configs={
            "codehilite": {
                "noclasses": True,
                "pygments_style": "default",
            }
        },
    )
    return f'<div class="markdown">{html}</div>'
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_render.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add src/assistant/ui/render.py tests/test_render.py
git commit -m "feat: markdown rendering with code highlighting"
```

---

### Task 9: 主窗口 UI（会话列表 + 对话区 + 流式聊天 + 设置对话框）

**Files:**
- Create: `src/assistant/ui/chat_view.py`
- Create: `src/assistant/ui/session_list.py`
- Create: `src/assistant/ui/settings_dialog.py`
- Create: `src/assistant/ui/main_window.py`
- Create: `src/assistant/main.py`
- Test: `tests/test_ui_smoke.py`

**Interfaces:**
- Consumes: `SessionManager`、`ChatService`、`EventBus`、`ConfigManager`、`SecretsStore`、`ProviderRegistry`、`render_markdown`
- Produces:
  - `ChatView`（QWidget）：`append_user(text)`、`append_assistant(text)`、`begin_stream()`（清空流式缓冲）、`on_delta(text)`、`end_stream()`
  - `SessionListWidget`（QListWidget）：`reload(sessions: list[Session])`、`select_session(session_id)`；信号 `session_selected = Signal(str)`、`session_create_requested = Signal()`、`session_rename_requested = Signal(str)`、`session_delete_requested = Signal(str)`、`search_changed = Signal(str)`
  - `SettingsDialog(cfg: AppConfig, secrets: SecretsStore, registry_provider_names: list[str])`（QDialog）：`exec()` 后调用 `result_config() -> AppConfig`、`result_api_key() -> str`（空串表示不变）
  - `MainWindow(sessions, chat, cfg, secrets)`（QMainWindow）
  - `main()` —— 装配并启动应用

- [ ] **Step 1: 写 UI 冒烟测试（QApplication 单例 + offscreen）**

`tests/test_ui_smoke.py`:
```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


def test_main_window_constructs(qapp):
    from assistant.core.chat import ChatService
    from assistant.core.sessions import SessionManager
    from assistant.storage.db import Database
    from assistant.ui.main_window import MainWindow

    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    chat = ChatService(sessions, provider=None, model=lambda: "deepseek-chat")
    win = MainWindow(sessions, chat, None, None)
    assert win.windowTitle() == "assistant"


def test_render_markdown_into_view(qapp):
    from assistant.ui.chat_view import ChatView
    view = ChatView()
    view.append_user("hi")
    view.on_delta("你好")
    view.end_stream()
    assert "你好" in view.browser.toPlainText()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_ui_smoke.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 chat_view.py**

`src/assistant/ui/chat_view.py`:
```python
import threading

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from assistant.ui.render import render_markdown


class ChatView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self._buffer = ""
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(80)
        self._flush_timer.timeout.connect(self._flush)

    def _flush(self):
        self.browser.setHtml(render_markdown(self._buffer))
        scrollbar = self.browser.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def append_user(self, text: str) -> None:
        self._buffer += f"\n\n### 🧑 你\n\n{text}\n\n"
        self._flush()

    def begin_stream(self) -> None:
        self._buffer += "\n\n### 🤖 assistant\n\n"

    def on_delta(self, text: str) -> None:
        self._buffer += text
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def end_stream(self) -> None:
        self._flush_timer.stop()
        self._flush()

    def clear_view(self) -> None:
        self._buffer = ""
        self._flush()
```

- [ ] **Step 4: 实现 session_list.py**

`src/assistant/ui/session_list.py`:
```python
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QVBoxLayout, QWidget,
)

from assistant.core.sessions import Session


class SessionListWidget(QWidget):
    session_selected = Signal(str)
    session_create_requested = Signal()
    session_rename_requested = Signal(str, str)   # (session_id, new_title)
    session_delete_requested = Signal(str)
    search_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索会话…")
        self.search_box.textChanged.connect(self.search_changed.emit)
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(
            lambda item: self.session_selected.emit(item.data(Qt.UserRole)))
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._menu)
        self.new_button = QPushButton("＋ 新会话")
        self.new_button.clicked.connect(self.session_create_requested.emit)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search_box)
        layout.addWidget(self.list_widget)
        layout.addWidget(self.new_button)

    def reload(self, sessions: list[Session]) -> None:
        self.list_widget.clear()
        for s in sessions:
            item = QListWidgetItem(s.title)
            item.setData(Qt.UserRole, s.id)
            self.list_widget.addItem(item)

    def select_session(self, session_id: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == session_id:
                self.list_widget.setCurrentItem(item)
                break

    def _menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        sid = item.data(Qt.UserRole)
        menu = QMenu(self)
        rename = menu.addAction("重命名")
        delete = menu.addAction("删除")
        action = menu.exec(self.list_widget.mapToGlobal(pos))
        if action == rename:
            title, ok = QInputDialog.getText(self, "重命名", "新标题：",
                                             text=item.text())
            if ok and title.strip():
                self.session_rename_requested.emit(sid, title.strip())
        elif action == delete:
            self.session_delete_requested.emit(sid)
```

- [ ] **Step 5: 实现 settings_dialog.py**

`src/assistant/ui/settings_dialog.py`:
```python
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QVBoxLayout,
)

from assistant.storage.config import AppConfig
from assistant.storage.secrets import SecretsStore


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, secrets: SecretsStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self._secrets = secrets
        self._cfg = cfg

        form = QFormLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        existing = secrets.get(cfg.models.provider) if secrets else None
        if existing:
            self.api_key.setPlaceholderText("已保存（留空保持不变）")
        self.base_url = QLineEdit(cfg.models.base_url)
        self.model = QLineEdit(cfg.models.model)
        self.task_model = QLineEdit(cfg.models.task_model)
        self.autopilot = QCheckBox("默认开启自动驾驶")
        self.autopilot.setChecked(cfg.autopilot_default)
        form.addRow("API Key", self.api_key)
        form.addRow("Base URL", self.base_url)
        form.addRow("聊天模型", self.model)
        form.addRow("任务模型", self.task_model)
        form.addRow("", self.autopilot)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_config(self) -> AppConfig:
        self._cfg.models.base_url = self.base_url.text().strip()
        self._cfg.models.model = self.model.text().strip() or "deepseek-chat"
        self._cfg.models.task_model = self.task_model.text().strip() or "deepseek-chat"
        self._cfg.autopilot_default = self.autopilot.isChecked()
        return self._cfg

    def result_api_key(self) -> str:
        return self.api_key.text().strip()

    def accept(self):
        key = self.result_api_key()
        if key and self._secrets:
            self._secrets.set(self._cfg.models.provider, key)
        super().accept()
```

- [ ] **Step 6: 实现 main_window.py + main.py**

`src/assistant/ui/main_window.py`:
```python
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

from assistant.core.chat import ChatService
from assistant.core.eventbus import EventBus
from assistant.core.sessions import Session, SessionManager
from assistant.storage.config import AppConfig
from assistant.storage.secrets import SecretsStore
from assistant.ui.chat_view import ChatView
from assistant.ui.session_list import SessionListWidget
from assistant.ui.settings_dialog import SettingsDialog


class _BusBridge(QObject):
    """把 EventBus 回调桥接到 Qt 主线程信号。"""
    chat_delta = Signal(str, str)      # session_id, text
    chat_done = Signal(str, str)       # session_id, full_reply
    chat_error = Signal(str, str)      # session_id, message


class MainWindow(QMainWindow):
    def __init__(self, sessions: SessionManager, chat: ChatService,
                 cfg: AppConfig | None, secrets: SecretsStore | None):
        super().__init__()
        self.setWindowTitle("assistant")
        self.resize(1000, 700)
        self.sessions = sessions
        self.chat = chat
        self.cfg = cfg or AppConfig()
        self.secrets = secrets
        self.current_session_id: str | None = None
        self.bus = EventBus()
        self.bridge = _BusBridge()
        self.bridge.chat_delta.connect(self._on_delta)
        self.bridge.chat_done.connect(self._on_done)
        self.bridge.chat_error.connect(self._on_error)
        self.bus.subscribe("chat.delta", lambda **kw: self.bridge.chat_delta.emit(
            kw["session_id"], kw["text"]))
        self.bus.subscribe("chat.done", lambda **kw: self.bridge.chat_done.emit(
            kw["session_id"], kw["reply"]))
        self.bus.subscribe("chat.error", lambda **kw: self.bridge.chat_error.emit(
            kw["session_id"], kw["message"]))

        self.session_list = SessionListWidget()
        self.session_list.session_selected.connect(self._select_session)
        self.session_list.session_create_requested.connect(self._create_session)
        self.session_list.session_rename_requested.connect(self._rename_session)
        self.session_list.session_delete_requested.connect(self._delete_session)
        self.session_list.search_changed.connect(self._search)

        self.chat_view = ChatView()
        self.input_box = QTextEdit()
        self.input_box.setPlaceholderText("输入消息，Ctrl+Enter 发送")
        self.input_box.setMaximumHeight(120)
        self.send_button = QPushButton("发送")
        self.send_button.clicked.connect(self._send)
        input_row = QHBoxLayout()
        input_row.addWidget(self.input_box, 1)
        input_row.addWidget(self.send_button)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(self.chat_view, 1)
        right_layout.addLayout(input_row)

        splitter = QSplitter()
        splitter.addWidget(self.session_list)
        splitter.addWidget(right)
        splitter.setSizes([220, 780])
        self.setCentralWidget(splitter)

        self._reload_sessions()
        settings_action = self.menuBar().addAction("设置")
        settings_action.triggered.connect(self._open_settings)

    # --- 会话管理 ---
    def _reload_sessions(self, query: str = ""):
        sessions = self.sessions.search(query) if query else self.sessions.list()
        self.session_list.reload(sessions)

    def _select_session(self, session_id: str):
        self.current_session_id = session_id
        self.chat_view.clear_view()
        for msg in self.sessions.history(session_id):
            if msg.role == "user":
                self.chat_view.append_user(msg.content)
            else:
                self.chat_view.begin_stream()
                self.chat_view.on_delta(msg.content)
                self.chat_view.end_stream()

    def _create_session(self):
        sid = self.sessions.create()
        self._reload_sessions()
        self.session_list.select_session(sid)
        self._select_session(sid)

    def _rename_session(self, session_id: str, title: str):
        self.sessions.rename(session_id, title)
        self._reload_sessions()

    def _delete_session(self, session_id: str):
        self.sessions.delete(session_id)
        if self.current_session_id == session_id:
            self.current_session_id = None
            self.chat_view.clear_view()
        self._reload_sessions()

    def _search(self, query: str):
        self._reload_sessions(query)

    # --- 聊天 ---
    def _send(self):
        if not self.current_session_id:
            self._create_session()
        text = self.input_box.toPlainText().strip()
        if not text:
            return
        self.input_box.clear()
        self.chat_view.append_user(text)
        self.chat_view.begin_stream()
        session_id = self.current_session_id
        self.send_button.setEnabled(False)

        def worker():
            try:
                reply = self.chat.stream_reply(
                    session_id, text,
                    on_delta=lambda t: self.bus.publish(
                        "chat.delta", session_id=session_id, text=t))
                self.bus.publish("chat.done", session_id=session_id, reply=reply)
            except Exception as exc:
                self.bus.publish("chat.error", session_id=session_id,
                                 message=str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_delta(self, session_id: str, text: str):
        if session_id == self.current_session_id:
            self.chat_view.on_delta(text)

    def _on_done(self, session_id: str, reply: str):
        if session_id == self.current_session_id:
            self.chat_view.end_stream()
        self.send_button.setEnabled(True)
        self._reload_sessions()

    def _on_error(self, session_id: str, message: str):
        self.send_button.setEnabled(True)
        QMessageBox.warning(self, "出错了", message)

    # --- 设置 ---
    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self.secrets, self)
        if dlg.exec():
            self.cfg = dlg.result_config()
            dlg.result_api_key()
```

`src/assistant/main.py`:
```python
import sys

from PySide6.QtWidgets import QApplication

from assistant.core.chat import ChatService
from assistant.core.sessions import SessionManager
from assistant.providers.registry import ProviderRegistry
from assistant.storage.config import ConfigManager
from assistant.storage.db import Database
from assistant.storage.paths import data_dir
from assistant.storage.secrets import SecretsStore, WindowsDpapiBackend
from assistant.ui.main_window import MainWindow


def _make_secrets() -> SecretsStore:
    import os
    if os.name == "nt":
        backend = WindowsDpapiBackend()
    else:
        class _PlainBackend:  # 开发用兜底，发布仅 Windows
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

    window = MainWindow(sessions, chat, cfg, secrets)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: 跑冒烟测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_ui_smoke.py -v`
Expected: 2 PASS

- [ ] **Step 8: 手工验证（开发机 Linux 上可跑，最终验证在 Windows）**

Run: `.venv/bin/python -m assistant`
Expected（按序检查）：
1. 窗口打开，标题 "assistant"，左侧会话列表可见
2. 点"＋ 新会话"创建会话
3. 在设置里填入 DeepSeek API key、确认 base_url 为 `https://api.deepseek.com/v1`、模型 `deepseek-chat`
4. 输入"你好"，Ctrl+Enter 发送 → 回复逐字流出、Markdown 正常渲染
5. 发一段含代码的问题 → 代码块高亮正常
6. 重启应用 → 历史会话与消息仍在
7. 右键会话 → 重命名/删除生效；搜索框能过滤会话
（无 API key 时跳过 4-5，检查 3、6、7）

- [ ] **Step 9: Commit**

```bash
git add src/assistant/ui src/assistant/main.py tests/test_ui_smoke.py
git commit -m "feat: main window with session list, streaming chat and settings"
```

---

## 计划完成标准

- [ ] `pytest` 全绿（`tests/` 下 9 个任务共 30 个测试）
- [ ] 手工验证清单全部通过
- [ ] 每条 task 已 commit
- [ ] Plan 2 可在此基座上开始（providers/chat/sessions 接口已冻结）
