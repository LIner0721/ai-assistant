import sys

import pytest

from assistant.core.platform import set_autostart


@pytest.mark.skipif(sys.platform == "win32",
                    reason="win32 需要真实注册表，手工验证")
def test_autostart_noop_on_non_windows():
    assert set_autostart(True) is False
    assert set_autostart(False) is False
