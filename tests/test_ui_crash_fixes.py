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
    """刷新会话列表不应触发会话切换（退回 bug 根因：reload 重填时
    Qt 会把 currentItem 恢复到原行号，而行序变了，导致选中另一个会话）。"""
    from assistant.core.sessions import Session
    from assistant.ui.session_list import SessionListWidget

    widget = SessionListWidget()
    widget.resize(220, 400)
    widget.show()                      # 真实显示状态才能复现
    qapp.processEvents()
    seen = []
    widget.session_selected.connect(seen.append)
    s1 = Session(id="old", title="旧会话", created_at="", updated_at="1")
    s2 = Session(id="cur", title="当前会话", created_at="", updated_at="2")
    widget.reload([s2, s1])
    qapp.processEvents()
    assert seen == []                  # 首次填充不自动选中
    widget.select_session("cur")
    qapp.processEvents()
    assert seen == ["cur"]
    # 回复完成后刷新：顺序不变，但 reload 不得发任何信号
    widget.reload([s2, s1])
    qapp.processEvents()
    assert seen == ["cur"]
    # 当前会话跳到顶部后刷新（真实排序场景）
    widget.reload([s2, s1])
    qapp.processEvents()
    assert seen == ["cur"]
    # 当前选中项高亮应保持在同一个会话上
    cur = widget.list_widget.currentItem()
    assert cur is not None and cur.data(0x0100) == "cur"


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
