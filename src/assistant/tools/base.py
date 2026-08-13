from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class RiskLevel(Enum):
    LOW = "low"
    HIGH = "high"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict   # JSON Schema
    risk: RiskLevel


@dataclass
class ToolResult:
    ok: bool
    output: str
    artifact: dict | None = None


class Tool(ABC):
    @property
    @abstractmethod
    def specs(self) -> list[ToolSpec]: ...

    @abstractmethod
    def execute(self, name: str, args: dict) -> ToolResult: ...
