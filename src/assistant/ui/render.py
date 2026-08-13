import markdown as md


def render_markdown(text: str) -> str:
    html = md.markdown(
        text,
        extensions=["fenced_code", "codehilite", "tables"],
        extension_configs={
            "codehilite": {
                "noclasses": True,
                "pygments_style": "default",
            }
        },
    )
    return f'<div class="markdown">{html}</div>'
