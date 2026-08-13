import sys


def set_autostart(enable: bool) -> bool:
    """开机自启（HKCU Run）。非 Windows 环境返回 False。"""
    if sys.platform != "win32":
        return False
    import winreg
    run_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0,
                             winreg.KEY_SET_VALUE)
    except OSError:
        return False
    try:
        if enable:
            exe = f'"{sys.executable}"'
            winreg.SetValueEx(key, "assistant", 0, winreg.REG_SZ, exe)
        else:
            try:
                winreg.DeleteValue(key, "assistant")
            except FileNotFoundError:
                pass
        return True
    finally:
        winreg.CloseKey(key)
