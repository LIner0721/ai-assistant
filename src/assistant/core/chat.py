from typing import Callable, Protocol

from assistant.core.sessions import SessionManager
from assistant.providers.base import ChatMessage, Provider


class SystemPromptFactory(Protocol):
    def __call__(self) -> str: ...


DEFAULT_PERSONA = (
    "你是 assistant，用户电脑上的私人 AI 助手。性格温和、可靠、偶尔幽默。"
    "回答用中文，简洁自然，像朋友一样。"
    "你有能力操作电脑（文件、应用、命令、浏览器），但只在用户要求时动手。"
)


class ChatService:
    history_limit = 20

    def __init__(
        self,
        sessions: SessionManager,
        provider: Provider,
        model: Callable[[], str],
        system_prompt: SystemPromptFactory | None = None,
    ):
        self.sessions = sessions
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt or (lambda: DEFAULT_PERSONA)

    def stream_reply(
        self,
        session_id: str,
        user_text: str,
        on_delta: Callable[[str], None],
    ) -> str:
        self.sessions.add_message(session_id, "user", user_text)
        history = self.sessions.history(session_id)
        messages = [ChatMessage("system", self.system_prompt())]
        messages += history[-self.history_limit:]
        completion = self.provider.chat(
            messages, model=self.model(), on_delta=on_delta)
        reply = completion.content
        if reply:
            self.sessions.add_message(session_id, "assistant", reply)
        return reply
