import base64
import json
from pathlib import Path
from typing import Protocol


class CryptoBackend(Protocol):
    def encrypt(self, data: bytes) -> bytes: ...
    def decrypt(self, data: bytes) -> bytes: ...


class WindowsDpapiBackend:
    """Windows DPAPI 加密。只在 Windows 上可实例化。"""

    def __init__(self) -> None:
        import win32crypt  # noqa: F401  # 延迟导入：pywin32 仅在 Windows extra 中
        self._win32crypt = win32crypt

    def encrypt(self, data: bytes) -> bytes:
        return self._win32crypt.CryptProtectData(data, None, None, None, None, 0)

    def decrypt(self, data: bytes) -> bytes:
        return self._win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]


class SecretsStore:
    def __init__(self, path: Path, backend: CryptoBackend):
        self.path = path
        self.backend = backend

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def set(self, name: str, value: str) -> None:
        data = self._read()
        data[name] = base64.b64encode(
            self.backend.encrypt(value.encode("utf-8"))).decode("ascii")
        self._write(data)

    def get(self, name: str) -> str | None:
        data = self._read()
        encoded = data.get(name)
        if encoded is None:
            return None
        return self.backend.decrypt(base64.b64decode(encoded)).decode("utf-8")

    def delete(self, name: str) -> None:
        data = self._read()
        if name in data:
            del data[name]
            self._write(data)
