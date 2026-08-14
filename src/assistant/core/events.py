from dataclasses import dataclass, field


@dataclass
class AgentEvent:
    type: str
    payload: dict = field(default_factory=dict)
