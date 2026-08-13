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
