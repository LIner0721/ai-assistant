import base64
import json

from assistant.storage.secrets import SecretsStore


class FakeBackend:
    def encrypt(self, data: bytes) -> bytes:
        return b"enc:" + data

    def decrypt(self, data: bytes) -> bytes:
        assert data.startswith(b"enc:")
        return data[4:]


def test_set_get_roundtrip(tmp_path):
    store = SecretsStore(tmp_path / "secrets.dat", FakeBackend())
    store.set("deepseek", "sk-test-123")
    assert store.get("deepseek") == "sk-test-123"


def test_get_missing_returns_none(tmp_path):
    store = SecretsStore(tmp_path / "secrets.dat", FakeBackend())
    assert store.get("nope") is None


def test_key_not_stored_in_plaintext(tmp_path):
    store = SecretsStore(tmp_path / "secrets.dat", FakeBackend())
    store.set("deepseek", "sk-secret-value")
    raw = (tmp_path / "secrets.dat").read_text(encoding="utf-8")
    assert "sk-secret-value" not in raw
    payload = json.loads(raw)
    assert base64.b64decode(payload["deepseek"]) == b"enc:sk-secret-value"


def test_delete(tmp_path):
    store = SecretsStore(tmp_path / "secrets.dat", FakeBackend())
    store.set("a", "1")
    store.delete("a")
    assert store.get("a") is None
