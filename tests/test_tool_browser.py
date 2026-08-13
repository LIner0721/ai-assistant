import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

_availability = None


def chromium_available() -> bool:
    global _availability
    if _availability is None:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                b.close()
            _availability = True
        except Exception:
            _availability = False
    return _availability


requires_chromium = pytest.mark.skipif(
    not chromium_available(),
    reason="chromium 无法启动（缺系统库或无沙箱），浏览器验证留待 Windows 终验")


def make_server(html):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


@requires_chromium
def test_fetch_page_extracts_markdown():
    server = make_server(
        "<html><head><title>测试页</title></head>"
        "<body><h1>标题</h1><p>这是正文内容，包含重要信息。</p>"
        "<script>var x=1;</script></body></html>")
    try:
        from assistant.tools.browser import BrowserTool
        tool = BrowserTool()
        r = tool.execute("fetch_page",
                         {"url": f"http://127.0.0.1:{server.server_port}/"})
        assert r.ok
        assert "标题" in r.output
        assert "重要信息" in r.output
    finally:
        server.shutdown()


@requires_chromium
def test_fetch_page_http_error():
    server = make_server("<html><body>not found</body></html>")
    try:
        from assistant.tools.browser import BrowserTool
        tool = BrowserTool()
        r = tool.execute("fetch_page", {"url": "http://127.0.0.1:1/nothing"})
        assert not r.ok or "无法" in r.output
    finally:
        server.shutdown()


def test_specs_low_risk():
    from assistant.tools.browser import BrowserTool
    from assistant.tools.base import RiskLevel
    assert all(s.risk is RiskLevel.LOW for s in BrowserTool().specs)
