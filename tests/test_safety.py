from assistant.agent.safety import Policy
from assistant.tools.base import RiskLevel


def test_low_risk_never_needs_confirmation():
    assert not Policy().needs_confirmation(RiskLevel.LOW)
    assert not Policy(autopilot=True).needs_confirmation(RiskLevel.LOW)


def test_high_risk_needs_confirmation_by_default():
    assert Policy().needs_confirmation(RiskLevel.HIGH)


def test_high_risk_passes_in_autopilot():
    assert not Policy(autopilot=True).needs_confirmation(RiskLevel.HIGH)


def test_set_autopilot():
    p = Policy()
    p.set_autopilot(True)
    assert not p.needs_confirmation(RiskLevel.HIGH)
    p.set_autopilot(False)
    assert p.needs_confirmation(RiskLevel.HIGH)
