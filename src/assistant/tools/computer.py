from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec

NOT_ENABLED = "键鼠控制将在后续版本启用（C 级能力）"


def _spec(name, desc):
    return ToolSpec(name=name, description=desc,
                    parameters={"type": "object", "properties": {}},
                    risk=RiskLevel.HIGH)


class ComputerTool(Tool):
    """C 级能力预留。v1 空实现；v1.5 起用 pynput 填充。"""

    @property
    def specs(self):
        return [
            _spec("click", "点击屏幕坐标 (x, y)。"),
            _spec("type_text", "输入文本到当前焦点窗口。"),
            _spec("move_mouse", "移动鼠标到 (x, y)。"),
            _spec("screenshot", "截取屏幕保存到文件。"),
        ]

    def execute(self, name, args):
        return ToolResult(ok=False, output=NOT_ENABLED)
