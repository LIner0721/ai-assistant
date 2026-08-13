from assistant.providers.base import Provider
from assistant.providers.openai_compat import OpenAICompatProvider


class ProviderRegistry:
    """openai-compat 适配器覆盖全部已知供应商，未来不兼容的再加专门适配器。"""

    _OPENAI_COMPAT = {"deepseek", "qwen", "kimi", "openai", "default"}

    def create(self, provider: str, base_url: str, api_key: str) -> Provider:
        if provider in self._OPENAI_COMPAT:
            return OpenAICompatProvider(base_url, api_key)
        raise ValueError(f"unknown provider: {provider}")
