"""粗略 token 估算,用于上下文预算。

DeepSeek 无官方 tokenizer 接口,采用通用近似:
中文每字 1 token,其余字符每 4 个 1 token。
"""


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - cjk
    return cjk + (other // 4) + (1 if other % 4 else 0)
