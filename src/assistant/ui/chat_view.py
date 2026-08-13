from PySide6.QtCore import QTimer
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
