import json
from dataclasses import dataclass

from assistant.providers.base import ChatMessage, Provider


@dataclass
class MemoryCandidate:
    type: str
    content: str
    importance: float


_EXTRACT_SYSTEM = (
    "从对话中提炼关于用户的长期记忆。只输出 JSON 数组，每个元素：\n"
    '{"type": "fact|preference|event", "content": "一句话记忆（第三人称，如：用户住在杭州）",'
    ' "importance": 0.0~1.0}\n'
    "没有值得记住的内容时输出 []。不要输出任何其他文字。"
)


class MemoryExtractor:
    def __init__(self, provider: Provider, model):
        self.provider = provider
        self.model = model

    def extract(self, conversation: list[ChatMessage]) -> list[MemoryCandidate]:
        try:
            result = self.provider.chat(
                [ChatMessage("system", _EXTRACT_SYSTEM),
                 ChatMessage("user", self._format(conversation))],
                model=self.model())
            return self._parse(result.content)
        except Exception:
            return []

    def _format(self, conversation) -> str:
        lines = [f"{m.role}: {m.content}" for m in conversation[-10:]]
        return "\n".join(lines)

    def _parse(self, text: str) -> list[MemoryCandidate]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            data = json.loads(cleaned)
            return [MemoryCandidate(
                type=str(item.get("type", "fact")),
                content=str(item["content"]),
                importance=float(item.get("importance", 0.5)))
                for item in data if isinstance(item, dict) and item.get("content")]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return []
