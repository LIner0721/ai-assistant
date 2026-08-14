from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from assistant.ui.render import (
    BG, render_assistant_block, render_markdown, render_note_block,
    render_reasoning_html, render_tool_block, render_user_block,
)

KIND_USER = "user"
KIND_ASSISTANT = "assistant"
KIND_TOOL = "tool"
KIND_NOTE = "note"


class ChatView(QWidget):
    """聊天视图：QQ 风格深色气泡，全部实时流式。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self._blocks: list[dict] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(80)
        self._flush_timer.timeout.connect(self._flush)

    # --- 块管理 ---
    def _assistant_block(self) -> dict:
        if not self._blocks or self._blocks[-1]["kind"] != KIND_ASSISTANT:
            self._blocks.append(
                {"kind": KIND_ASSISTANT, "text": "", "reasoning": ""})
        return self._blocks[-1]

    def _append(self, kind: str, text: str) -> dict:
        if not self._blocks or self._blocks[-1]["kind"] != kind:
            self._blocks.append({"kind": kind, "text": ""})
        self._blocks[-1]["text"] += text
        return self._blocks[-1]

    def _schedule_flush(self) -> None:
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush(self):
        parts = []
        for b in self._blocks:
            kind = b["kind"]
            if kind == KIND_USER:
                parts.append(render_user_block(
                    render_markdown(b["text"])))
            elif kind == KIND_ASSISTANT:
                if b["reasoning"]:
                    parts.append(render_reasoning_html(b["reasoning"]))
                parts.append(render_assistant_block(
                    render_markdown(b["text"])))
            elif kind == KIND_TOOL:
                parts.append(render_tool_block(b["text"]))
            else:
                parts.append(render_note_block(b["text"]))
        self.browser.setHtml(
            f'<body style="background-color:{BG}">'
            f'{"".join(parts)}</body>')
        scrollbar = self.browser.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # --- 对外 API ---
    def append_user(self, text: str) -> None:
        self._append(KIND_USER, text)
        self._flush()

    def begin_stream(self) -> None:
        self._assistant_block()

    def on_reasoning(self, text: str) -> None:
        self._assistant_block()["reasoning"] += text
        self._schedule_flush()

    def on_delta(self, text: str) -> None:
        self._assistant_block()["text"] += text
        self._schedule_flush()

    def end_stream(self) -> None:
        self._flush_timer.stop()
        self._flush()

    def clear_view(self) -> None:
        self._blocks = []
        self._flush()

    def on_task_event(self, event) -> None:
        etype, payload = event.type, event.payload
        if etype == "text":
            self.on_delta(payload.get("text", ""))
        elif etype == "reasoning":
            self.on_reasoning(payload.get("text", ""))
        elif etype == "tool_start":
            name = payload.get("name") or "..."
            self._append(KIND_TOOL, f"调用 {name} {payload.get('args', '')}")
        elif etype == "tool_args":
            self._append(KIND_TOOL, payload.get("args_delta", ""))
        elif etype == "step_start":
            self._append(KIND_NOTE,
                         f"▶ 第 {payload['step']} 步：{payload['tool']}")
        elif etype == "step_end":
            icon = {"ok": "✅", "failed": "❌", "declined": "🚫"}.get(
                payload.get("status"), "•")
            self._append(KIND_NOTE, f"{icon} 第 {payload['step']} 步完成")
        elif etype == "done":
            self._append(KIND_NOTE, f"✅ {payload.get('summary', '')}")
        elif etype == "failed":
            self._append(KIND_NOTE, f"❌ {payload.get('summary', '')}")
        else:
            return
        self._flush()
