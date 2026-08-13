from enum import Enum
from typing import Callable

from assistant.providers.base import ChatMessage, Provider


class Intent(Enum):
    CHAT = "chat"
    TASK = "task"


_SYSTEM = (
    "判断用户输入属于哪一类：\n"
    "- TASK：要求你操作电脑完成实际工作（操作文件、启动/关闭程序、"
    "执行命令、搜索或抓取网页、整理资料等）\n"
    "- CHAT：普通聊天、情感交流、问答、咨询、闲聊\n"
    "只回答一个词：TASK 或 CHAT。"
)


class IntentClassifier:
    def __init__(self, provider: Provider, model: Callable[[], str]):
        self.provider = provider
        self.model = model

    def classify(self, text: str) -> Intent:
        try:
            result = self.provider.chat(
                [ChatMessage("system", _SYSTEM),
                 ChatMessage("user", text)],
                model=self.model())
            answer = result.content.strip().upper()
            return Intent.TASK if answer == "TASK" else Intent.CHAT
        except Exception:
            return Intent.CHAT
