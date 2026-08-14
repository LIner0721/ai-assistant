import os
import sys

from PySide6.QtWidgets import QApplication

from assistant.agent.engine import AgentEngine
from assistant.agent.recorder import TaskRecorder
from assistant.agent.safety import Policy
from assistant.core.chat import ChatService
from assistant.core.intent import IntentClassifier
from assistant.core.sessions import SessionManager
from assistant.core.tasks import TaskRouter
from assistant.memory.extract import MemoryExtractor
from assistant.memory.persona import PersonaManager
from assistant.memory.resolve import MemoryResolver
from assistant.memory.retrieve import MemoryRetriever
from assistant.memory.store import MemoryStore
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
from assistant.ui.hotkey import HotkeyManager
from assistant.ui.main_window import MainWindow
from assistant.ui.tray import TrayIcon


def _thinking(mode: str) -> str | None:
    """把配置的思考模式映射为 provider 参数：auto 不注入。"""
    return None if mode in ("", "auto") else mode


def _make_secrets() -> SecretsStore:
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

    persona = PersonaManager(db)
    memory_store = MemoryStore(db)
    retriever = MemoryRetriever(memory_store)
    extractor = MemoryExtractor(provider, model=lambda: cfg.models.model)
    resolver = MemoryResolver(memory_store)

    chat = ChatService(sessions, provider, model=lambda: cfg.models.model,
                       system_prompt=persona.active,
                       retriever=retriever, extractor=extractor,
                       resolver=resolver,
                       thinking=lambda: _thinking(cfg.models.thinking_mode))

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
            stop=lambda: window._stop_flag.is_set(),
            thinking=lambda: _thinking(cfg.models.thinking_mode))

    router = TaskRouter(chat, classifier, make_engine, sessions)
    window = MainWindow(sessions, chat, cfg, secrets, router,
                        persona=persona, memory_store=memory_store)

    tray = TrayIcon(window, policy, cfg, on_quit=lambda: (
        tray.hide(), app.quit()))
    window.tray = tray
    tray.show()

    app.setQuitOnLastWindowClosed(False)
    if cfg.autostart:
        from assistant.core.platform import set_autostart
        set_autostart(True)   # 应用内幂等刷新

    hotkey = HotkeyManager(cfg.hotkey, on_activate=lambda: (
        window.show() if window.isHidden() else window.hide()))
    hotkey.start()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
