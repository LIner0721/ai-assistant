from assistant.storage.config import AppConfig, ConfigManager


def test_load_missing_file_returns_defaults(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cfg = cm.load()
    assert cfg.models.model == "deepseek-chat"
    assert cfg.models.base_url == "https://api.deepseek.com/v1"
    assert cfg.hotkey == "<ctrl>+<alt>+<space>"
    assert cfg.autopilot_default is False


def test_save_and_load_roundtrip(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cfg = AppConfig()
    cfg.models.model = "qwen-plus"
    cfg.autopilot_default = True
    cm.save(cfg)
    loaded = cm.load()
    assert loaded.models.model == "qwen-plus"
    assert loaded.autopilot_default is True


def test_load_partial_json_fills_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"hotkey": "<ctrl>+<shift>+a"}', encoding="utf-8")
    cfg = ConfigManager(p).load()
    assert cfg.hotkey == "<ctrl>+<shift>+a"
    assert cfg.models.model == "deepseek-chat"


def test_load_corrupt_json_returns_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("not json{{", encoding="utf-8")
    cfg = ConfigManager(p).load()
    assert cfg.models.model == "deepseek-chat"
