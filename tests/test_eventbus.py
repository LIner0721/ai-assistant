import threading

from assistant.core.eventbus import EventBus


def test_publish_delivers_payload():
    bus = EventBus()
    got = []
    bus.subscribe("chat.delta", lambda text, **kw: got.append(text))
    bus.publish("chat.delta", text="hello")
    assert got == ["hello"]


def test_bad_handler_does_not_block_others():
    bus = EventBus()
    got = []

    def bad(**kw):
        raise RuntimeError("boom")

    bus.subscribe("t", bad)
    bus.subscribe("t", lambda **kw: got.append(1))
    bus.publish("t")
    assert got == [1]


def test_cross_thread_publish():
    bus = EventBus()
    got = []
    bus.subscribe("t", lambda v, **kw: got.append(v))
    t = threading.Thread(target=lambda: bus.publish("t", v=42))
    t.start()
    t.join()
    assert got == [42]
