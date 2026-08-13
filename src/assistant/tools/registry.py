from assistant.tools.base import RiskLevel, Tool, ToolSpec


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, tuple[Tool, ToolSpec]] = {}

    def register(self, tool: Tool) -> None:
        for spec in tool.specs:
            self._tools[spec.name] = (tool, spec)

    def get(self, name: str) -> tuple[Tool, ToolSpec]:
        return self._tools[name]

    def risk_of(self, name: str) -> RiskLevel:
        return self._tools[name][1].risk

    def list_specs(self) -> list[dict]:
        return [
            {"type": "function",
             "function": {"name": spec.name, "description": spec.description,
                          "parameters": spec.parameters}}
            for _, (_tool, spec) in sorted(self._tools.items())
        ]
