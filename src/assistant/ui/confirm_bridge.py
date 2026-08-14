"""把工具确认对话框安全地搬到主线程执行。

引擎在后台线程调用 confirm()；Qt 禁止在非主线程创建窗口，
因此 confirm() 通过信号把请求投递到主线程弹出对话框，
后台线程阻塞等待结果。
"""
import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal

from assistant.agent.safety import ConfirmationRequest


class ConfirmBridge(QObject):
    requested = Signal(object)   # ConfirmationRequest

    def __init__(self, window=None,
                 dialog: Callable[[ConfirmationRequest, object], bool] | None
                 = None):
        super().__init__()
        self.window = window
        # dialog 可注入（测试用）；默认用 ConfirmDialog
        self._dialog = dialog
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._result = False
        self.requested.connect(self._show_dialog)

    def confirm(self, request: ConfirmationRequest) -> bool:
        with self._lock:
            self._ready.clear()
            self.requested.emit(request)   # 跨线程排队到主线程
        self._ready.wait()
        with self._lock:
            return self._result

    def _show_dialog(self, request: ConfirmationRequest) -> None:
        try:
            if self._dialog is not None:
                ok = self._dialog(request, self.window)
            else:
                from assistant.ui.confirm_dialog import ConfirmDialog
                ok = ConfirmDialog(request, self.window).exec() == 1
        finally:
            with self._lock:
                self._result = ok
                self._ready.set()
