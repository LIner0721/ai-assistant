from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from assistant.agent.safety import Policy
from assistant.storage.config import AppConfig


def _icon() -> QIcon:
    from PySide6.QtGui import QPixmap
    pm = QPixmap(64, 64)
    pm.fill(Qt.darkCyan)
    return QIcon(pm)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, policy: Policy, cfg: AppConfig, on_quit):
        super().__init__(_icon(), window)
        self.window = window
        self.policy = policy
        self.cfg = cfg
        self.on_quit = on_quit

        menu = QMenu()
        show_action = QAction("显示主窗口", menu)
        show_action.triggered.connect(self._show)
        self.autopilot_action = QAction("自动驾驶", menu)
        self.autopilot_action.setCheckable(True)
        self.autopilot_action.setChecked(cfg.autopilot_default)
        self.autopilot_action.toggled.connect(self._toggle_autopilot)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(on_quit)
        menu.addAction(show_action)
        menu.addAction(self.autopilot_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.setContextMenu(menu)
        self.activated.connect(self._activated)

    def _show(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def _toggle_autopilot(self, on: bool):
        self.policy.set_autopilot(on)
        self.cfg.autopilot_default = on
        self.showMessage("assistant", "自动驾驶已开启" if on else "自动驾驶已关闭")

    def _activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._show()
