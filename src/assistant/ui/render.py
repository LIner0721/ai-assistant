"""聊天区 HTML 渲染：QQ 风格深色气泡。"""
import html as _html

import markdown as md

ACCENT = "#12B7F5"       # QQ 蓝
BG = "#1e1e22"           # 主背景
BUBBLE_AI = "#2a2a30"    # AI 气泡
PANEL = "#26262b"        # 面板
TEXT = "#e8e8ea"
TEXT_DIM = "#9a9aa3"
NOTE_BG = "#33333a"


def render_markdown(text: str) -> str:
    html = md.markdown(
        text,
        extensions=["fenced_code", "codehilite", "tables"],
        extension_configs={
            "codehilite": {
                "noclasses": True,
                "pygments_style": "monokai",
            }
        },
    )
    return f'<div class="markdown">{html}</div>'


def render_reasoning_html(text: str) -> str:
    """思考过程：气泡上方的独立灰条。"""
    body = _html.escape(text).replace("\n", "<br>")
    return (
        f'<div style="color:{TEXT_DIM};font-size:9pt;'
        f'background-color:{NOTE_BG};border-radius:10px;'
        f'padding:6px 10px;margin-left:38px;margin-bottom:2px;">'
        f'🧠 思考：{body}</div>'
    )


def render_assistant_block(body_html: str) -> str:
    """AI 消息：左侧深灰圆角气泡，🤖 头像。"""
    return (
        '<table width="100%" cellspacing="0" cellpadding="4"><tr>'
        '<td width="30" valign="top">🤖</td>'
        f'<td style="background-color:{BUBBLE_AI};color:{TEXT};'
        'border-radius:14px;padding:10px 14px;">'
        f'{body_html}</td>'
        '<td width="15%"></td>'
        '</tr></table>'
    )


def render_user_block(body_html: str) -> str:
    """用户消息：右侧 QQ 蓝圆角气泡，🧑 头像。"""
    return (
        '<table width="100%" cellspacing="0" cellpadding="4"><tr>'
        '<td width="30%"></td>'
        f'<td style="background-color:{ACCENT};color:#ffffff;'
        'border-radius:14px;padding:10px 14px;">'
        f'{body_html}</td>'
        '<td width="30" valign="top">🧑</td>'
        '</tr></table>'
    )


def render_tool_block(text: str) -> str:
    body = _html.escape(text).replace("\n", "<br>")
    return (
        f'<div style="color:{TEXT_DIM};font-family:monospace;'
        f'font-size:9pt;background-color:{PANEL};border-radius:10px;'
        f'padding:6px 10px;margin:4px 0;">🔧 {body}</div>'
    )


def render_note_block(text: str) -> str:
    body = _html.escape(text).replace("\n", "<br>")
    return (
        f'<div style="color:{TEXT_DIM};font-size:9pt;'
        f'padding:4px 8px;">{body}</div>'
    )
