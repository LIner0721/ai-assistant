import os
from pathlib import Path

APP_NAME = "assistant"


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path.home() / ".assistant"
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d
