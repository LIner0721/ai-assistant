from assistant.storage.config import AppConfig, ConfigManager


def test_load_missing_file_returns_defaults(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cfg = cm.load()
    assert cfg.models.model == "deepseek-chat"
    assert cfg.models.base_url == "https://api.deepseek.com/v1"
    assert cfg.models.thinking_mode == "auto"
    assert cfg.hotkey == "<ctrl>+<alt>+<space>"
    assert cfg.autopilot_default is False


def test_save_and_load_roundtrip(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cfg = AppConfig()
    cfg.models.model = "qwen-plus"
    cfg.models.thinking_mode = "enabled"
    cfg.autopilot_default = True
    cm.save(cfg)
    loaded = cm.load()
    assert loaded.models.model == "qwen-plus"
    assert loaded.models.thinking_mode == "enabled"
    assert loaded.autopilot_default is True


def test_load_partial_json_fills_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text('{"hotkey": "<ctrl>+<shift>+a"}', encoding="utf-8")
    cfg = ConfigManager(p).load()
    assert cfg.hotkey == "<ctrl>+<shift>+a"
    assert cfg.models.model == "deepseek-chat"


def test_context_limit_default_and_roundtrip(tmp_path):
    cm = ConfigManager(tmp_path / "config.json")
    cfg = cm.load()
    assert cfg.context_limit_tokens == 65536
    cfg.context_limit_tokens = 131072
    cm.save(cfg)
    assert cm.load().context_limit_tokens == 131072


def test_load_corrupt_json_returns_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("not json{{", encoding="utf-8")
    cfg = ConfigManager(p).load()
    assert cfg.models.model == "deepseek-chat"
