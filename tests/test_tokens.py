from assistant.core.tokens import estimate_tokens


def test_empty():
    assert estimate_tokens("") == 0


def test_cjk_chars_count_one_each():
    assert estimate_tokens("你好世界") == 4


def test_ascii_chars_four_per_token():
    assert estimate_tokens("abcdefgh") == 2   # 8 字符 / 4


def test_mixed():
    # 2 个中文 + 8 个英文 = 2 + 2
    assert estimate_tokens("你好abcdefgh") == 4
