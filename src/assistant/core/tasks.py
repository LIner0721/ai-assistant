import logging
from typing import Callable

from assistant.agent.engine import AgentEngine, AgentEvent, TaskReport
from assistant.core.chat import ChatService
from assistant.core.intent import Intent, IntentClassifier
from assistant.core.sessions import SessionManager

log = logging.getLogger("assistant.tasks")


class TaskRouter:
    def __init__(self, chat: ChatService, classifier: IntentClassifier,
                 engine_factory: Callable[[], AgentEngine],
                 sessions: SessionManager):
        self.chat = chat
        self.classifier = classifier
        self.engine_factory = engine_factory
        self.sessions = sessions

    def route(self, session_id: str, text: str,
              on_delta: Callable[[str], None],
              on_event: Callable[[AgentEvent], None],
              on_reasoning: Callable[[str], None] | None = None,
              ) -> str | TaskReport:
        intent = self.classifier.classify(text)
        log.info("route session=%s intent=%s text=%r",
                 session_id, intent, text[:80])
        if intent is Intent.CHAT:
            return self.chat.stream_reply(session_id, text, on_delta,
                                          on_reasoning=on_reasoning)
        self.sessions.add_message(session_id, "user", text)
        engine = self.engine_factory()
        engine.on_event = on_event   # 把事件回调接进引擎，干活过程才能实时显示
        report = engine.run_task(text, session_id=session_id)
        if report.summary:
            self.sessions.add_message(session_id, "assistant", report.summary)
        return report
