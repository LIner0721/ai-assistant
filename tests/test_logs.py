import logging

from assistant.core.logs import get_logger


def test_logger_writes_to_file(tmp_path):
    logger = get_logger(tmp_path)
    logger.info("启动 assistant，版本 0.2.0")
    # 幂等：重复调用返回同一个 logger，不重复加 handler
    same = get_logger(tmp_path)
    assert same is logger
    for h in logger.handlers:
        h.flush()
    text = (tmp_path / "assistant.log").read_text(encoding="utf-8")
    assert "启动 assistant，版本 0.2.0" in text
    assert "INFO" in text


def test_provider_logs_stream_stats(caplog):
    import json
    import httpx

    from assistant.providers.base import ChatMessage
    from assistant.providers.openai_compat import OpenAICompatProvider

    def _sse(payloads):
        lines = [f"data: {json.dumps(p)}" for p in payloads]
        lines.append("data: [DONE]")
        return "\n\n".join(lines).encode("utf-8")

    def handler(request: httpx.Request):
        return httpx.Response(200, content=_sse([
            {"choices": [{"delta": {"reasoning_content": "想"}}]},
            {"choices": [{"delta": {"content": "你"}}]},
            {"choices": [{"delta": {"content": "好"}}]},
        ]))

    provider = OpenAICompatProvider("https://api.deepseek.com/v1", "sk-test")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.INFO, logger="assistant.provider"):
        provider.chat([ChatMessage("user", "hi")], model="deepseek-chat",
                      on_delta=lambda t: None, on_reasoning=lambda t: None,
                      thinking="enabled")
    joined = "\n".join(r.message for r in caplog.records)
    assert "stream" in joined and "chunks" in joined
