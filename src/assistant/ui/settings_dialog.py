import json

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from assistant.storage.config import AppConfig
from assistant.storage.secrets import SecretsStore


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, secrets: SecretsStore,
                 persona=None, store=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self._secrets = secrets
        self._cfg = cfg
        self._persona = persona
        self._store = store
        self.resize(560, 420)

        tabs = QTabWidget()
        tabs.addTab(self._model_tab(), "模型")
        tabs.addTab(self._persona_tab(), "人设")
        tabs.addTab(self._memory_tab(), "记忆")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def _model_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        if self._secrets:
            existing = self._secrets.get(self._cfg.models.provider)
            if existing:
                self.api_key.setPlaceholderText("已保存（留空保持不变）")
        self.base_url = QLineEdit(self._cfg.models.base_url)
        self.model = QLineEdit(self._cfg.models.model)
        self.task_model = QLineEdit(self._cfg.models.task_model)
        self.thinking_mode = QComboBox()
        self.thinking_mode.addItem("自动", "auto")
        self.thinking_mode.addItem("开启", "enabled")
        self.thinking_mode.addItem("关闭", "disabled")
        self.thinking_mode.setCurrentIndex(
            self.thinking_mode.findData(self._cfg.models.thinking_mode))
        self.autopilot = QCheckBox("默认开启自动驾驶")
        self.autopilot.setChecked(self._cfg.autopilot_default)
        self.autostart_check = QCheckBox("开机自启")
        self.autostart_check.setChecked(self._cfg.autostart)
        form.addRow("API Key", self.api_key)
        form.addRow("Base URL", self.base_url)
        form.addRow("聊天模型", self.model)
        form.addRow("任务模型", self.task_model)
        form.addRow("思考模式", self.thinking_mode)
        form.addRow("", self.autopilot)
        form.addRow("", self.autostart_check)
        return w

    def _persona_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel("预置人设："))
        self.persona_combo = QComboBox()
        if self._persona:
            self.persona_combo.addItems(self._persona.list_presets())
            self.persona_combo.setCurrentText(self._persona.current_preset())
        row.addWidget(self.persona_combo, 1)
        layout.addLayout(row)
        layout.addWidget(QLabel("自定义 system prompt（留空使用预置）："))
        self.custom_prompt = QPlainTextEdit()
        if self._persona:
            custom = self._persona._get(self._persona.KEY_CUSTOM)
            if custom:
                self.custom_prompt.setPlainText(custom)
        layout.addWidget(self.custom_prompt)
        return w

    def _memory_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        self.memory_list = QListWidget()
        self._reload_memories()
        layout.addWidget(self.memory_list)
        row = QHBoxLayout()
        delete_btn = QPushButton("删除选中")
        delete_btn.clicked.connect(self._delete_selected)
        export_btn = QPushButton("导出 JSON")
        export_btn.clicked.connect(self._export)
        clear_btn = QPushButton("清空全部")
        clear_btn.clicked.connect(self._clear_all)
        row.addWidget(delete_btn)
        row.addWidget(export_btn)
        row.addWidget(clear_btn)
        layout.addLayout(row)
        return w

    def _reload_memories(self):
        self.memory_list.clear()
        if self._store:
            for m in self._store.list_all():
                self.memory_list.addItem(f"[{m.type}] {m.content}")

    def _delete_selected(self):
        if not self._store:
            return
        memories = self._store.list_all()
        row = self.memory_list.currentRow()
        if 0 <= row < len(memories):
            self._store.delete(memories[row].id)
            self._reload_memories()

    def _export(self):
        if not self._store:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出记忆", "memories.json")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._store.export(), f, ensure_ascii=False, indent=2)

    def _clear_all(self):
        if not self._store:
            return
        if QMessageBox.question(self, "确认", "清空全部记忆？此操作不可撤销。") \
                == QMessageBox.Yes:
            self._store.clear()
            self._reload_memories()

    def result_config(self) -> AppConfig:
        self._cfg.models.base_url = self.base_url.text().strip()
        self._cfg.models.model = self.model.text().strip() or "deepseek-chat"
        self._cfg.models.task_model = self.task_model.text().strip() or "deepseek-chat"
        self._cfg.models.thinking_mode = self.thinking_mode.currentData() or "auto"
        self._cfg.autopilot_default = self.autopilot.isChecked()
        self._cfg.autostart = self.autostart_check.isChecked()
        return self._cfg

    def result_api_key(self) -> str:
        return self.api_key.text().strip()

    def result_persona(self):
        if not self._persona:
            return
        self._persona.set_preset(self.persona_combo.currentText())
        self._persona.set_custom(self.custom_prompt.toPlainText().strip())

    def accept(self):
        key = self.result_api_key()
        if key and self._secrets:
            self._secrets.set(self._cfg.models.provider, key)
        self.result_persona()
        super().accept()
