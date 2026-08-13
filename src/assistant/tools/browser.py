import threading

import trafilatura
from playwright.sync_api import sync_playwright

from assistant.tools.base import RiskLevel, Tool, ToolResult, ToolSpec

FETCH_LIMIT = 20000
SEARCH_RESULT_LIMIT = 8


class BrowserTool(Tool):
    def __init__(self):
        self._lock = threading.Lock()
        self._pw = None
        self._browser = None

    _install_attempted = False

    def _ensure_browser(self):
        if self._browser is None:
            self._pw = sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch(headless=True)
            except Exception as exc:
                if "Executable doesn't exist" in str(exc) \
                        and not self._install_attempted:
                    self._install_attempted = True
                    import subprocess
                    import sys
                    subprocess.run(
                        [sys.executable, "-m", "playwright", "install",
                         "chromium"], check=False)
                    self._browser = self._pw.chromium.launch(headless=True)
                else:
                    raise

    @property
    def specs(self):
        return [
            ToolSpec(name="search_web", description="搜索网页，返回结果列表（标题、链接、摘要）。",
                     parameters={"type": "object",
                                 "properties": {"query": {"type": "string"}},
                                 "required": ["query"]},
                     risk=RiskLevel.LOW),
            ToolSpec(name="fetch_page", description="打开网页并提取正文（Markdown）。",
                     parameters={"type": "object",
                                 "properties": {"url": {"type": "string"}},
                                 "required": ["url"]},
                     risk=RiskLevel.LOW),
        ]

    def execute(self, name, args):
        with self._lock:  # Playwright sync API 必须同一线程串行使用
            try:
                self._ensure_browser()
                if name == "search_web":
                    return self._search(args["query"])
                if name == "fetch_page":
                    return self._fetch(args["url"])
                return ToolResult(ok=False, output=f"未知函数: {name}")
            except Exception as exc:
                return ToolResult(ok=False, output=f"浏览器操作失败: {exc}")

    def _search(self, query: str) -> ToolResult:
        page = self._browser.new_page()
        try:
            page.goto(f"https://www.bing.com/search?q={query}",
                      timeout=30000)
            results = page.eval_on_selector_all(
                "li.b_algo",
                """els => els.slice(0, 8).map(el => {
                    const a = el.querySelector('h2 a');
                    const p = el.querySelector('p');
                    return {title: a ? a.innerText : '',
                            url: a ? a.href : '',
                            snippet: p ? p.innerText : ''};
                })""")
        finally:
            page.close()
        if not results:
            return ToolResult(ok=True, output="(没有搜到结果)")
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
        return ToolResult(ok=True, output="\n".join(lines))

    def _fetch(self, url: str) -> ToolResult:
        page = self._browser.new_page()
        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            html = page.content()
        finally:
            page.close()
        text = trafilatura.extract(html, output_format="markdown",
                                   include_comments=False)
        if not text:
            text = trafilatura.extract(html) or "(页面没有可提取的正文)"
        if len(text) > FETCH_LIMIT:
            text = text[:FETCH_LIMIT] + "\n…(内容过长，已截断)"
        return ToolResult(ok=True, output=text)

    def close(self):
        with self._lock:
            if self._browser:
                self._browser.close()
                self._pw.stop()
                self._browser = None
                self._pw = None
