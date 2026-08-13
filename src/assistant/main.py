import sys

from PySide6.QtWidgets import QApplication

from assistant.core.chat import ChatService
from assistant.core.sessions import SessionManager
from assistant.providers.registry import ProviderRegistry
from assistant.storage.config import ConfigManager
from assistant.storage.db import Database
from assistant.storage.paths import data_dir
from assistant.storage.secrets import SecretsStore, WindowsDpapiBackend
from assistant.ui.main_window import MainWindow


def _make_secrets() -> SecretsStore:
    import os
    if os.name == "nt":
        backend = WindowsDpapiBackend()
    else:
        class _PlainBackend:  # 开发用兜底，发布仅 Windows
            def encrypt(self, data: bytes) -> bytes:
                return data

            def decrypt(self, data: bytes) -> bytes:
                return data
        backend = _PlainBackend()
    return SecretsStore(data_dir() / "secrets.dat", backend)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("assistant")

    cfg = ConfigManager(data_dir() / "config.json").load()
    db = Database(data_dir() / "assistant.db")
    db.migrate()
    secrets = _make_secrets()

    registry = ProviderRegistry()
    provider = registry.create(
        cfg.models.provider, cfg.models.base_url,
        secrets.get(cfg.models.provider) or "")

    sessions = SessionManager(db)
    chat = ChatService(sessions, provider, model=lambda: cfg.models.model)

    window = MainWindow(sessions, chat, cfg, secrets)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
