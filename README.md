# assistant

Windows 个人 AI 助手：聊天陪伴（人设 + 长期记忆）+ 系统级干活 agent。

## 功能
- 聊天：DeepSeek 默认，流式输出，Markdown 渲染
- 干活：文件操作、启动/关闭应用、PowerShell、浏览器搜索与抓取
- 多步任务：目标 → 自动拆解 → 执行 → 失败自纠 → 汇报
- 长期记忆：自动沉淀、冲突消解、检索注入（本地 SQLite，可导出/清空）
- 人设：预置 3 套 + 自定义 system prompt
- 托盘常驻、全局热键（Ctrl+Alt+Space）、开机自启
- 安全：高风控操作确认 + 自动驾驶开关

## 开发
```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"   # Windows: .venv\Scripts\
.venv/bin/playwright install chromium
.venv/bin/python -m pytest
.venv/bin/python -m assistant
```

## 构建（Windows 10/11 64 位）
```bash
pip install -e ".[dev, windows]"
python build.py          # 产物 dist/assistant.exe
```

## 使用
1. 首次启动进入设置，填入 DeepSeek API Key（默认 base_url https://api.deepseek.com/v1）
2. 首次使用浏览器功能会自动下载 chromium（约 150MB）
3. 数据存于 %APPDATA%\assistant\（数据库、配置、密钥）
