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
