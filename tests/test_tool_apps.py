import subprocess
import sys as _sys

from assistant.tools.apps import AppsTool
from assistant.tools.base import RiskLevel


def test_launch_resolves_from_path(monkeypatch, tmp_path):
    fake = tmp_path / "notepad"
    fake.write_text("#!/bin/sh\necho hi\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=":")
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kw):
            calls.append(cmd)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    tool = AppsTool()
    r = tool.execute("launch_app", {"name_or_path": "notepad"})
    assert r.ok and "已启动" in r.output
    assert calls and calls[0][-1] == str(fake)   # 解析到了 PATH 中的可执行文件


def test_close_app_windows_style(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "SUCCESS: 已终止", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(_sys, "platform", "win32")  # 实现里用 sys.platform 判断
    tool = AppsTool()
    r = tool.execute("close_app", {"name": "notepad.exe"})
    assert r.ok
    assert any("taskkill" in c[0] for c in calls)


def test_close_app_missing_process(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 128, "", "没有找到进程")

    monkeypatch.setattr(subprocess, "run", fake_run)
    tool = AppsTool()
    r = tool.execute("close_app", {"name": "ghost.exe"})
    assert not r.ok


def test_risks():
    by_name = {s.name: s.risk for s in AppsTool().specs}
    assert by_name["launch_app"] is RiskLevel.LOW
    assert by_name["close_app"] is RiskLevel.HIGH
