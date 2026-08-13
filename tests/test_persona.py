from assistant.core.chat import DEFAULT_PERSONA
from assistant.memory.persona import PRESET_PERSONAS, PersonaManager
from assistant.storage.db import Database


def make():
    db = Database(":memory:")
    db.migrate()
    return PersonaManager(db)


def test_default_active_is_default_persona():
    pm = make()
    assert pm.active() == DEFAULT_PERSONA


def test_set_preset():
    pm = make()
    pm.set_preset("温柔陪伴")
    assert pm.active() == PRESET_PERSONAS["温柔陪伴"]
    assert pm.current_preset() == "温柔陪伴"


def test_custom_overrides_preset():
    pm = make()
    pm.set_preset("高效干练")
    pm.set_custom("你是一只猫。")
    assert pm.active() == "你是一只猫。"


def test_clear_custom_restores_preset():
    pm = make()
    pm.set_preset("高效干练")
    pm.set_custom("你是一只猫。")
    pm.set_custom("")
    assert pm.active() == PRESET_PERSONAS["高效干练"]


def test_persists_across_instances():
    db = Database(":memory:")
    db.migrate()
    PersonaManager(db).set_preset("温柔陪伴")
    assert PersonaManager(db).active() == PRESET_PERSONAS["温柔陪伴"]
