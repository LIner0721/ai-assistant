from assistant.ui.render import (
    render_assistant_block, render_markdown, render_reasoning_html,
    render_tool_block, render_user_block,
)


def test_plain_text():
    html = render_markdown("你好")
    assert "你好" in html
    assert html.startswith("<div")


def test_code_block_highlighted():
    html = render_markdown("```python\nprint(1)\n```")
    # codehilite + noclasses=True 生成内联样式的高亮代码块
    assert "codehilite" in html
    assert "print" in html


def test_inline_formatting():
    html = render_markdown("**加粗** 和 `代码`")
    assert "<strong>" in html
    assert "<code>" in html


def test_user_block_is_right_blue_bubble():
    html = render_user_block("<p>你好</p>")
    assert "你好" in html
    assert "#12B7F5" in html
    # 右侧气泡：先有一个空列，气泡列在其后
    assert html.index('width="30%"') < html.index("#12B7F5")


def test_assistant_block_is_left_gray_bubble():
    html = render_assistant_block("<p>好</p>")
    assert "好" in html
    assert "#2a2a30" in html


def test_reasoning_html_gray_small():
    html = render_reasoning_html("让我想想")
    assert "🧠" in html
    assert "让我想想" in html
    assert "#9a9aa3" in html


def test_tool_block_monospace():
    html = render_tool_block("调用 echo")
    assert "调用 echo" in html
    assert "monospace" in html
