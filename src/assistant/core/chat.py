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

MEMORY_SECTION = "\n\n关于用户的长期记忆（仅供参考，不要主动提起）：\n{memories}"


class ChatService:
    history_limit = 20

    def __init__(
        self,
        sessions: SessionManager,
        provider: Provider,
        model: Callable[[], str],
        system_prompt: SystemPromptFactory | None = None,
        retriever=None,      # MemoryRetriever | None
        extractor=None,      # MemoryExtractor | None
        resolver=None,       # MemoryResolver | None
    ):
        self.sessions = sessions
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt or (lambda: DEFAULT_PERSONA)
        self.retriever = retriever
        self.extractor = extractor
        self.resolver = resolver

    def _build_system(self, user_text: str) -> str:
        base = self.system_prompt()
        if not self.retriever:
            return base
        memories = self.retriever.retrieve(user_text, k=8)
        if not memories:
            return base
        lines = "\n".join(f"- {m.content}" for m in memories)
        return base + MEMORY_SECTION.format(memories=lines)

    def stream_reply(
        self,
        session_id: str,
        user_text: str,
        on_delta: Callable[[str], None],
    ) -> str:
        self.sessions.add_message(session_id, "user", user_text)
        history = self.sessions.history(session_id)
        messages = [ChatMessage("system", self._build_system(user_text))]
        messages += history[-self.history_limit:]
        completion = self.provider.chat(
            messages, model=self.model(), on_delta=on_delta)
        reply = completion.content
        if reply:
            self.sessions.add_message(session_id, "assistant", reply)
            self._update_memories(session_id, user_text, reply)
        return reply

    def _update_memories(self, session_id, user_text, reply) -> None:
        if not (self.extractor and self.resolver):
            return
        try:
            candidates = self.extractor.extract([
                ChatMessage("user", user_text),
                ChatMessage("assistant", reply),
            ])
            if candidates:
                self.resolver.apply(candidates, source_session=session_id)
        except Exception:
            pass  # 记忆沉淀失败不影响聊天
