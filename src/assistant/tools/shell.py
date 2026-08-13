import subprocess
import sys

from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec

TIMEOUT = 60
OUTPUT_LIMIT = 8000


class ShellTool(Tool):
    @property
    def specs(self):
        return [
            ToolSpec(name="run_command", description="执行一条系统命令（Windows: PowerShell；其他: sh）。禁止交互式命令。",
                     parameters={"type": "object",
                                 "properties": {"command": {"type": "string"}},
                                 "required": ["command"]},
                     risk=RiskLevel.HIGH),
        ]

    def execute(self, name, args):
        try:
            if sys.platform == "win32":
                cmd = ["powershell", "-NoProfile", "-Command", args["command"]]
            else:
                cmd = ["sh", "-c", args["command"]]
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, output=f"命令执行超时（>{TIMEOUT}s），已终止")
        except Exception as exc:
            return ToolResult(ok=False, output=f"命令执行失败: {exc}")

        output = (proc.stdout or "") + (proc.stderr or "")
        if len(output) > OUTPUT_LIMIT:
            output = output[:OUTPUT_LIMIT] + "\n…(输出过长，已截断)"
        ok = proc.returncode == 0
        head = "执行成功" if ok else "执行失败"
        return ToolResult(ok=ok, output=f"{head}（退出码 {proc.returncode}）\n{output}")
