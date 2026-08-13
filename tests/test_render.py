from assistant.ui.render import render_markdown


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
