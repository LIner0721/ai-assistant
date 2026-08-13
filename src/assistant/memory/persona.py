from assistant.core.chat import DEFAULT_PERSONA
from assistant.storage.db import Database

PRESET_PERSONAS: dict[str, str] = {
    "默认助理": DEFAULT_PERSONA,
    "温柔陪伴": (
        "你是 assistant，用户最贴心的陪伴。语气温柔、有耐心，"
        "善于倾听和共情。回答用中文，像老朋友聊天。"
        "能帮用户干活，但重点是让人感到被理解和陪伴。"
    ),
    "高效干练": (
        "你是 assistant，一位高效的执行助理。回答简短、直接、"
        "条理清晰，用最少的话把事情说清楚。优先给结论，再给细节。"
        "干活时汇报进度与结果，不废话。"
    ),
}


class PersonaManager:
    KEY_PRESET = "persona_preset"
    KEY_CUSTOM = "persona_custom"

    def __init__(self, db: Database):
        self.db = db

    def _get(self, key: str) -> str | None:
        row = self.db.query_one(
            "SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else None

    def _set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value))

    def list_presets(self) -> list[str]:
        return list(PRESET_PERSONAS)

    def current_preset(self) -> str:
        return self._get(self.KEY_PRESET) or "默认助理"

    def set_preset(self, name: str) -> None:
        if name not in PRESET_PERSONAS:
            raise ValueError(f"未知人设: {name}")
        self._set(self.KEY_PRESET, name)

    def set_custom(self, text: str) -> None:
        if text.strip():
            self._set(self.KEY_CUSTOM, text.strip())
        else:
            self.db.execute("DELETE FROM settings WHERE key=?",
                            (self.KEY_CUSTOM,))

    def active(self) -> str:
        custom = self._get(self.KEY_CUSTOM)
        if custom:
            return custom
        return PRESET_PERSONAS.get(self.current_preset(), DEFAULT_PERSONA)
