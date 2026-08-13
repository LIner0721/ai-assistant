import subprocess
import sys

from assistant.tools.base import RiskLevel
from assistant.tools.shell import ShellTool


def test_run_command_success(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        assert kw["timeout"] == 60
        return subprocess.CompletedProcess(cmd, 0, "hello world", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ShellTool().execute("run_command", {"command": "echo hi"})
    assert r.ok
    assert "hello world" in r.output
    assert "退出码 0" in r.output


def test_run_command_failure(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "command not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ShellTool().execute("run_command", {"command": "nope"})
    assert not r.ok
    assert "command not found" in r.output


def test_output_truncated(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, "x" * 20000, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ShellTool().execute("run_command", {"command": "big"})
    assert len(r.output) < 9000
    assert "截断" in r.output


def test_timeout(monkeypatch):
    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ShellTool().execute("run_command", {"command": "sleep 100"})
    assert not r.ok
    assert "超时" in r.output


def test_windows_uses_powershell(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "platform", "win32")
    ShellTool().execute("run_command", {"command": "Get-Date"})
    assert calls[0][0] == "powershell"
    assert calls[0][1] == "-NoProfile"


def test_risk_high():
    assert ShellTool().specs[0].risk is RiskLevel.HIGH
