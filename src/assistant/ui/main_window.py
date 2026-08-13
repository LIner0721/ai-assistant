import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

from assistant.core.chat import ChatService
from assistant.core.eventbus import EventBus
from assistant.core.sessions import SessionManager
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
    task_event = Signal(str, object)   # session_id, AgentEvent


class MainWindow(QMainWindow):
    def __init__(self, sessions: SessionManager, chat: ChatService,
                 cfg: AppConfig | None, secrets: SecretsStore | None,
                 router=None, persona=None, memory_store=None):
        super().__init__()
        self.setWindowTitle("assistant")
        self.resize(1000, 700)
        self.sessions = sessions
        self.chat = chat
        self.cfg = cfg or AppConfig()
        self.secrets = secrets
        self.router = router
        self.persona = persona
        self.memory_store = memory_store
        self.current_session_id: str | None = None
        self._stop_flag = threading.Event()
        self.bus = EventBus()
        self.bridge = _BusBridge()
        self.bridge.chat_delta.connect(self._on_delta)
        self.bridge.chat_done.connect(self._on_done)
        self.bridge.chat_error.connect(self._on_error)
        self.bridge.task_event.connect(self._on_task_event)
        self.bus.subscribe("chat.delta", lambda **kw: self.bridge.chat_delta.emit(
            kw["session_id"], kw["text"]))
        self.bus.subscribe("chat.done", lambda **kw: self.bridge.chat_done.emit(
            kw["session_id"], kw["reply"]))
        self.bus.subscribe("chat.error", lambda **kw: self.bridge.chat_error.emit(
            kw["session_id"], kw["message"]))
        self.bus.subscribe("task.event", lambda **kw: self.bridge.task_event.emit(
            kw["session_id"], kw["event"]))

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
        self.stop_button = QPushButton("停止")
        self.stop_button.setVisible(False)
        self.stop_button.clicked.connect(self.stop_requested)
        input_row = QHBoxLayout()
        input_row.addWidget(self.input_box, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.stop_button)
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

    # --- 发送（双线路由） ---
    def _send(self):
        if not self.current_session_id:
            self._create_session()
        if not self.router:
            self._send_chat_only()
            return
        text = self.input_box.toPlainText().strip()
        if not text:
            return
        self.input_box.clear()
        self.chat_view.append_user(text)
        self.chat_view.begin_stream()
        session_id = self.current_session_id
        self.send_button.setEnabled(False)
        self.stop_button.setVisible(True)
        self._stop_flag.clear()

        def worker():
            try:
                result = self.router.route(
                    session_id, text,
                    on_delta=lambda t: self.bus.publish(
                        "chat.delta", session_id=session_id, text=t),
                    on_event=lambda ev: self.bus.publish(
                        "task.event", session_id=session_id, event=ev))
                reply = result.summary if hasattr(result, "summary") else result
                self.bus.publish("chat.done", session_id=session_id,
                                 reply=reply)
            except Exception as exc:
                self.bus.publish("chat.error", session_id=session_id,
                                 message=str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _send_chat_only(self):
        """无路由时的降级路径（测试/占位）。"""
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

    def stop_requested(self):
        self._stop_flag.set()

    def _on_delta(self, session_id: str, text: str):
        if session_id == self.current_session_id:
            self.chat_view.on_delta(text)

    def _on_task_event(self, session_id, event):
        if session_id == self.current_session_id:
            self.chat_view.on_task_event(event)

    def _on_done(self, session_id: str, reply: str):
        if session_id == self.current_session_id:
            self.chat_view.end_stream()
        self.send_button.setEnabled(True)
        self.stop_button.setVisible(False)
        self._reload_sessions()

    def _on_error(self, session_id: str, message: str):
        self.send_button.setEnabled(True)
        self.stop_button.setVisible(False)
        QMessageBox.warning(self, "出错了", message)

    # --- 设置 ---
    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self.secrets, self.persona,
                             self.memory_store, self)
        if dlg.exec():
            self.cfg = dlg.result_config()
            dlg.result_api_key()
            from assistant.core.platform import set_autostart
            set_autostart(self.cfg.autostart)

    def closeEvent(self, event):
        # 关闭 = 隐藏到托盘（由 main.py 注入 tray）
        if getattr(self, "tray", None) and self.tray.isVisible():
            event.ignore()
            self.hide()
        else:
            event.accept()
