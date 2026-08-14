import json
import logging
import time

import httpx

from assistant.providers.base import (
    ChatMessage, Completion, Provider, ToolCall, ToolCallDelta,
)

log = logging.getLogger("assistant.provider")


class OpenAICompatProvider(Provider):
    """OpenAI 兼容协议适配器：DeepSeek / 通义 / Kimi 通用。"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0))

    def chat(self, messages, model, tools=None, on_delta=None,
             on_reasoning=None, on_tool_delta=None, thinking=None) -> Completion:
        t0 = time.time()
        payload = {
            "model": model,
            "messages": [m.to_openai() for m in messages],
        }
        if tools:
            payload["tools"] = tools
        if thinking:
            payload["thinking"] = {"type": thinking}
        if on_delta is not None:
            payload["stream"] = True
        log.info("request model=%s stream=%s thinking=%s tools=%d msgs=%d",
                 model, on_delta is not None, thinking,
                 len(tools or []), len(messages))
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
        if on_delta is not None:
            completion = self._parse_stream(response, on_delta,
                                            on_reasoning, on_tool_delta)
        else:
            completion = self._parse_once(response)
        log.info("done model=%s elapsed=%.2fs content=%d reasoning=%d "
                 "tool_calls=%d",
                 model, time.time() - t0, len(completion.content),
                 len(completion.reasoning), len(completion.tool_calls))
        return completion

    def _parse_once(self, response: httpx.Response) -> Completion:
        data = response.json()
        message = data["choices"][0]["message"]
        tool_calls = [
            ToolCall(id=t["id"], name=t["function"]["name"],
                     arguments=json.loads(t["function"]["arguments"] or "{}"))
            for t in (message.get("tool_calls") or [])
        ]
        return Completion(content=message.get("content") or "",
                          tool_calls=tool_calls,
                          reasoning=message.get("reasoning_content") or "")

    def _parse_stream(self, response: httpx.Response, on_delta,
                      on_reasoning, on_tool_delta) -> Completion:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_buf: dict[int, dict] = {}
        chunks = 0
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            chunks += 1
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
                on_delta(delta["content"])
            if delta.get("reasoning_content"):
                reasoning_parts.append(delta["reasoning_content"])
                if on_reasoning:
                    on_reasoning(delta["reasoning_content"])
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                buf = tool_buf.setdefault(idx, {
                    "id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    buf["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    buf["name"] = fn["name"]
                if fn.get("arguments"):
                    buf["arguments"] += fn["arguments"]
                if on_tool_delta:
                    on_tool_delta(ToolCallDelta(
                        index=idx, id=tc.get("id", ""),
                        name=fn.get("name", ""),
                        arguments_delta=fn.get("arguments", "")))
        tool_calls = [
            ToolCall(id=b["id"], name=b["name"],
                     arguments=json.loads(b["arguments"] or "{}"))
            for _, b in sorted(tool_buf.items())
        ]
        log.info("stream chunks=%d content_chunks=%d reasoning_chunks=%d",
                 chunks, len(content_parts), len(reasoning_parts))
        return Completion(content="".join(content_parts), tool_calls=tool_calls,
                          reasoning="".join(reasoning_parts))
