import shutil
import subprocess
import sys

from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec


class AppsTool(Tool):
    @property
    def specs(self):
        return [
            ToolSpec(name="launch_app", description="启动一个应用（可执行名或完整路径）。",
                     parameters={"type": "object",
                                 "properties": {"name_or_path": {"type": "string"}},
                                 "required": ["name_or_path"]},
                     risk=RiskLevel.LOW),
            ToolSpec(name="close_app", description="关闭一个正在运行的进程（进程名，如 notepad.exe）。",
                     parameters={"type": "object",
                                 "properties": {"name": {"type": "string"}},
                                 "required": ["name"]},
                     risk=RiskLevel.HIGH),
        ]

    def execute(self, name, args):
        try:
            if name == "launch_app":
                return self._launch(args["name_or_path"])
            if name == "close_app":
                return self._close(args["name"])
            return ToolResult(ok=False, output=f"未知函数: {name}")
        except Exception as exc:
            return ToolResult(ok=False, output=f"操作失败: {exc}")

    def _launch(self, target: str) -> ToolResult:
        resolved = shutil.which(target) or target
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", resolved],
                             shell=False)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", resolved])
        else:
            subprocess.Popen(["xdg-open", resolved])
        return ToolResult(ok=True, output=f"已启动 {target}")

    def _close(self, name: str) -> ToolResult:
        if sys.platform == "win32":
            cmd = ["taskkill", "/F", "/IM", name]
        else:
            cmd = ["pkill", "-f", name]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            return ToolResult(ok=False,
                              output=f"关闭失败: {proc.stderr.strip() or '进程不存在'}")
        return ToolResult(ok=True, output=f"已关闭 {name}")
