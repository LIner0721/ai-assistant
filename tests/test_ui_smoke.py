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
    win = MainWindow(sessions, chat, None, None, router=None)
    assert win.windowTitle().startswith("assistant v")


def test_status_bar_shows_state_and_context(qapp):
    from assistant.core.chat import ChatService
    from assistant.core.sessions import SessionManager
    from assistant.storage.db import Database
    from assistant.ui.main_window import MainWindow

    db = Database(":memory:")
    db.migrate()
    sessions = SessionManager(db)
    chat = ChatService(sessions, provider=None, model=lambda: "deepseek-chat")
    win = MainWindow(sessions, chat, None, None, router=None)
    assert win.status_text() == "空闲"
    assert win.context_text() == "上下文 0/20"
    sid = sessions.create()
    win._reload_sessions()
    win.session_list.select_session(sid)
    assert win.context_text() == "上下文 0/20"
    sessions.add_message(sid, "user", "你好")
    sessions.add_message(sid, "assistant", "你好呀")
    win._select_session(sid)   # 回复完成后的刷新路径
    assert win.context_text() == "上下文 2/20"
    win.set_running("思考中…")
    assert win.status_text() == "思考中…"


def test_render_markdown_into_view(qapp):
    from assistant.ui.chat_view import ChatView
    view = ChatView()
    view.append_user("hi")
    view.on_delta("你好")
    view.end_stream()
    assert "你好" in view.browser.toPlainText()


def test_chat_view_task_events(qapp):
    from assistant.agent.engine import AgentEvent
    from assistant.ui.chat_view import ChatView
    view = ChatView()
    view.on_task_event(AgentEvent("text", {"text": "计划内容"}))
    view.on_task_event(AgentEvent("step_start",
                                  {"step": 1, "tool": "echo"}))
    view.on_task_event(AgentEvent("step_end",
                                  {"step": 1, "tool": "echo",
                                   "status": "ok"}))
    view.on_task_event(AgentEvent("done", {"summary": "完成"}))
    text = view.browser.toPlainText()
    assert "计划内容" in text
    assert "echo" in text
    assert "完成" in text


def test_chat_view_streams_reasoning_and_tool_calls(qapp):
    from assistant.agent.engine import AgentEvent
    from assistant.ui.chat_view import ChatView
    view = ChatView()
    view.begin_stream()
    view.on_reasoning("让我")
    view.on_reasoning("想想")
    view.on_delta("答案是 42")
    view.on_task_event(AgentEvent("tool_start",
                                  {"index": 0, "name": "echo",
                                   "args": "", "args_delta": ""}))
    view.on_task_event(AgentEvent("tool_args",
                                  {"index": 0, "name": "echo",
                                   "args": "{\"text\":",
                                   "args_delta": "{\"text\":"}))
    view.on_task_event(AgentEvent("tool_args",
                                  {"index": 0, "name": "echo",
                                   "args": "{\"text\":\"hi\"}",
                                   "args_delta": "\"hi\"}"}))
    view.end_stream()
    text = view.browser.toPlainText()
    assert "让我想想" in text
    assert "答案是 42" in text
    assert "echo" in text
    assert "hi" in text


def test_chat_view_uses_qq_theme_bubbles(qapp):
    """用户消息右侧蓝色气泡、AI 左侧灰色气泡、思考块灰色小字。"""
    from assistant.ui.chat_view import ChatView
    view = ChatView()
    view.append_user("你好")
    view.begin_stream()
    view.on_reasoning("让我想想")
    view.on_delta("答案是 42")
    view.end_stream()
    html = view.browser.toHtml().lower()
    assert "#12b7f5" in html           # QQ 蓝（用户气泡）
    assert "#2a2a30" in html           # AI 深灰气泡
    assert "#1e1e22" in html           # 深色背景
    assert "🧠" in html
    text = view.browser.toPlainText()
    assert "让我想想" in text and "答案是 42" in text


def test_settings_dialog_thinking_mode(qapp):
    from assistant.storage.config import AppConfig
    from assistant.ui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(AppConfig(), None, parent=None)
    combo = dlg.thinking_mode
    assert combo.currentData() == "auto"
    combo.setCurrentIndex(combo.findData("enabled"))
    cfg = dlg.result_config()
    assert cfg.models.thinking_mode == "enabled"
