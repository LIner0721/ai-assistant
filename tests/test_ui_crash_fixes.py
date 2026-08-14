import threading

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


def test_confirm_bridge_runs_dialog_on_main_thread(qapp):
    """确认对话框必须在主线程弹出，否则 Qt 崩溃（闪退根因）。"""
    import time

    from assistant.agent.safety import ConfirmationRequest
    from assistant.ui.confirm_bridge import ConfirmBridge

    calls = []

    def fake_dialog(request, parent):
        calls.append(threading.current_thread())
        return False

    bridge = ConfirmBridge(dialog=fake_dialog)
    result = {}

    t = threading.Thread(
        target=lambda: result.setdefault("r", bridge.confirm(
            ConfirmationRequest("shell", {"cmd": "dir"}))))
    t.start()
    # 主线程必须泵事件，排队信号才能送达并执行弹窗
    while t.is_alive():
        qapp.processEvents()
        time.sleep(0.01)
    t.join(timeout=5)
    assert result["r"] is False
    assert calls and calls[0] is threading.main_thread()


def test_session_list_reload_does_not_emit_selection(qapp):
    """刷新会话列表不应触发会话切换（退回 bug 根因）。"""
    from assistant.core.sessions import Session
    from assistant.ui.session_list import SessionListWidget

    widget = SessionListWidget()
    seen = []
    widget.session_selected.connect(seen.append)
    s1 = Session(id="a", title="会话A", created_at="", updated_at="")
    s2 = Session(id="b", title="会话B", created_at="", updated_at="")
    widget.reload([s1, s2])
    assert seen == []                       # reload 不得发选中信号
    widget.select_session("b")
    assert seen == ["b"]                    # 主动选中才发信号
    widget.reload([s2, s1])
    assert seen == ["b"]                    # 再次 reload 仍不发信号


def test_excepthook_logs_crash_traceback(tmp_path):
    """未捕获异常要写进日志，否则 exe 闪退没有现场。"""
    import time

    from assistant.core.logs import get_logger, install_excepthook

    logger = get_logger(tmp_path)
    install_excepthook(logger)

    def boom():
        raise RuntimeError("模拟闪退")

    t = threading.Thread(target=boom)
    t.start()
    t.join(timeout=5)
    time.sleep(0.2)
    for h in logger.handlers:
        h.flush()
    text = (tmp_path / "assistant.log").read_text(encoding="utf-8")
    assert "模拟闪退" in text
    assert "Traceback" in text
