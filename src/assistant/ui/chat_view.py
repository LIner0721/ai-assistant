import html

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from assistant.ui.render import render_markdown

KIND_MARKDOWN = "markdown"
KIND_REASONING = "reasoning"
KIND_TOOL = "tool"


class ChatView(QWidget):
    """聊天视图：按块渲染（markdown / 思考过程 / 工具调用），全部实时流式。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self._blocks: list[list] = []   # [kind, text]
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(80)
        self._flush_timer.timeout.connect(self._flush)

    def _append(self, kind: str, text: str) -> None:
        if not self._blocks or self._blocks[-1][0] != kind:
            self._blocks.append([kind, ""])
        self._blocks[-1][1] += text

    def _flush(self):
        parts = []
        for kind, text in self._blocks:
            if kind == KIND_REASONING:
                body = html.escape(text).replace("\n", "<br>")
                parts.append(
                    f'<div style="color:#808080;font-size:9pt">'
                    f"🧠 思考：{body}</div>")
            elif kind == KIND_TOOL:
                body = html.escape(text).replace("\n", "<br>")
                parts.append(
                    f'<div style="color:#808080;'
                    f'font-family:monospace;font-size:9pt">🔧 {body}</div>')
            else:
                parts.append(render_markdown(text))
        self.browser.setHtml("".join(parts))
        scrollbar = self.browser.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def append_user(self, text: str) -> None:
        self._append(KIND_MARKDOWN, f"\n\n### 🧑 你\n\n{text}\n\n")
        self._flush()

    def begin_stream(self) -> None:
        self._append(KIND_MARKDOWN, "\n\n### 🤖 assistant\n\n")

    def on_reasoning(self, text: str) -> None:
        self._append(KIND_REASONING, text)
        self._schedule_flush()

    def on_delta(self, text: str) -> None:
        self._append(KIND_MARKDOWN, text)
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def end_stream(self) -> None:
        self._flush_timer.stop()
        self._flush()

    def clear_view(self) -> None:
        self._blocks = []
        self._flush()

    def on_task_event(self, event) -> None:
        etype, payload = event.type, event.payload
        if etype == "text":
            self._append(KIND_MARKDOWN, payload.get("text", ""))
        elif etype == "reasoning":
            self._append(KIND_REASONING, payload.get("text", ""))
        elif etype == "tool_start":
            name = payload.get("name") or "..."
            self._append(KIND_TOOL, f"调用 {name} {payload.get('args', '')}")
        elif etype == "tool_args":
            self._append(KIND_TOOL, payload.get("args_delta", ""))
        elif etype == "step_start":
            self._append(KIND_MARKDOWN, f"\n▶ **第 {payload['step']} 步**："
                                        f"`{payload['tool']}`\n")
        elif etype == "step_end":
            icon = {"ok": "✅", "failed": "❌", "declined": "🚫"}.get(
                payload.get("status"), "•")
            self._append(KIND_MARKDOWN,
                         f"{icon} 第 {payload['step']} 步完成\n")
        elif etype == "done":
            self._append(KIND_MARKDOWN,
                         f"\n\n---\n\n✅ {payload.get('summary', '')}\n")
        elif etype == "failed":
            self._append(KIND_MARKDOWN,
                         f"\n\n❌ {payload.get('summary', '')}\n")
        else:
            return
        self._flush()
