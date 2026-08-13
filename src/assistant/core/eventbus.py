import threading
import traceback
from collections import defaultdict
from typing import Callable


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Callable) -> None:
        with self._lock:
            self._handlers[topic].append(handler)

    def publish(self, topic: str, **payload) -> None:
        with self._lock:
            handlers = list(self._handlers.get(topic, ()))
        for handler in handlers:
            try:
                handler(**payload)
            except Exception:
                traceback.print_exc()
