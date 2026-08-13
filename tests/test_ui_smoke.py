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
    assert win.windowTitle() == "assistant"


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
    view.on_task_event(AgentEvent("plan", {"plan": "计划内容"}))
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
