import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class ModelConfig:
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    task_model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    thinking_mode: str = "auto"   # auto / enabled / disabled


@dataclass
class AppConfig:
    models: ModelConfig = field(default_factory=ModelConfig)
    hotkey: str = "<ctrl>+<alt>+<space>"
    autopilot_default: bool = False
    autostart: bool = False
    context_limit_tokens: int = 65536


def _fill(dc, data: dict):
    for f in fields(dc):
        if f.name in data:
            value = data[f.name]
            if isinstance(getattr(dc, f.name), ModelConfig) and isinstance(value, dict):
                value = _fill(ModelConfig(), value)
            setattr(dc, f.name, value)
    return dc


class ConfigManager:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> AppConfig:
        cfg = AppConfig()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return cfg
        if isinstance(data, dict):
            _fill(cfg, data)
        return cfg

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2),
            encoding="utf-8")
