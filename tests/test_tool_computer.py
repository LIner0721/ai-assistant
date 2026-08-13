from assistant.tools.base import RiskLevel
from assistant.tools.computer import ComputerTool


def test_specs_exist_and_high_risk():
    names = {s.name for s in ComputerTool().specs}
    assert {"click", "type_text", "move_mouse", "screenshot"} <= names
    assert all(s.risk is RiskLevel.HIGH for s in ComputerTool().specs)


def test_execute_returns_not_enabled():
    r = ComputerTool().execute("click", {"x": 10, "y": 20})
    assert not r.ok
    assert "后续版本" in r.output
