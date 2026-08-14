from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

import json


@dataclass
class ChatMessage:
    role: str
    content: str
    tool_calls: list = None
    tool_call_id: str | None = None

    def to_openai(self) -> dict:
        m: dict = {"role": self.role, "content": self.content or ""}
        if self.tool_calls:
            m["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name,
                              "arguments": json.dumps(tc.arguments,
                                                      ensure_ascii=False)}}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            m["tool_call_id"] = self.tool_call_id
        return m


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Completion:
    content: str = ""
    tool_calls: list = field(default_factory=list)
    reasoning: str = ""


@dataclass
class ToolCallDelta:
    """流式工具调用的一个增量片段。"""
    index: int
    id: str = ""
    name: str = ""
    arguments_delta: str = ""


class Provider(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list,
        model: str,
        tools: list | None = None,
        on_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        on_tool_delta: Callable[[ToolCallDelta], None] | None = None,
        thinking: str | None = None,
    ):
        """调用模型。on_delta 提供时走流式，每个文本增量回调一次。

        on_reasoning 接收思考过程增量，on_tool_delta 接收工具调用增量。
        thinking 为 "enabled"/"disabled" 时向请求注入对应参数，None 时不注入。
        """
