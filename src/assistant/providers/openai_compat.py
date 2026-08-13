import json

import httpx

from assistant.providers.base import ChatMessage, Completion, Provider, ToolCall


class OpenAICompatProvider(Provider):
    """OpenAI 兼容协议适配器：DeepSeek / 通义 / Kimi 通用。"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0))

    def chat(self, messages, model, tools=None, on_delta=None) -> Completion:
        payload = {
            "model": model,
            "messages": [m.to_openai() for m in messages],
        }
        if tools:
            payload["tools"] = tools
        if on_delta is not None:
            payload["stream"] = True
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        response.raise_for_status()
        if on_delta is not None:
            return self._parse_stream(response, on_delta)
        return self._parse_once(response)

    def _parse_once(self, response: httpx.Response) -> Completion:
        data = response.json()
        message = data["choices"][0]["message"]
        tool_calls = [
            ToolCall(id=t["id"], name=t["function"]["name"],
                     arguments=json.loads(t["function"]["arguments"] or "{}"))
            for t in (message.get("tool_calls") or [])
        ]
        return Completion(content=message.get("content") or "",
                          tool_calls=tool_calls)

    def _parse_stream(self, response: httpx.Response, on_delta) -> Completion:
        content_parts: list[str] = []
        tool_buf: dict[int, dict] = {}
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
                on_delta(delta["content"])
            for tc in delta.get("tool_calls") or []:
                buf = tool_buf.setdefault(tc["index"], {
                    "id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    buf["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    buf["name"] = fn["name"]
                if fn.get("arguments"):
                    buf["arguments"] += fn["arguments"]
        tool_calls = [
            ToolCall(id=b["id"], name=b["name"],
                     arguments=json.loads(b["arguments"] or "{}"))
            for _, b in sorted(tool_buf.items())
        ]
        return Completion(content="".join(content_parts), tool_calls=tool_calls)
