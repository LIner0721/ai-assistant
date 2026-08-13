import threading
from typing import Callable


class HotkeyManager:
    """pynput 全局热键。监听器启动失败（无桌面环境）静默禁用。"""

    def __init__(self, hotkey: str, on_activate: Callable[[], None]):
        self.hotkey = hotkey
        self.on_activate = on_activate
        self._listener = None
        self._thread = None

    def start(self) -> bool:
        if not self.hotkey or self._listener:
            return False
        try:
            from pynput import keyboard
            self._listener = keyboard.GlobalHotKeys(
                {self.hotkey: self.on_activate})
            self._thread = threading.Thread(
                target=self._listener.run, daemon=True)
            self._thread.start()
            return True
        except Exception:
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
