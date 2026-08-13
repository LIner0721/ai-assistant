from dataclasses import dataclass
from typing import Protocol

from assistant.tools.base import RiskLevel


@dataclass
class ConfirmationRequest:
    tool_name: str
    args: dict
    session_id: str | None = None


class ConfirmCallback(Protocol):
    def __call__(self, request: ConfirmationRequest) -> bool: ...


class Policy:
    def __init__(self, autopilot: bool = False):
        self._autopilot = autopilot

    def set_autopilot(self, on: bool) -> None:
        self._autopilot = on

    def needs_confirmation(self, risk: RiskLevel) -> bool:
        return (not self._autopilot) and risk is RiskLevel.HIGH
