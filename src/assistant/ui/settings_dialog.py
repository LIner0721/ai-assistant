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
