"""Shared tokenizers for BM25 index and query — must be identical on both
sides. `keep_whitespace` default in pythainlp is True, which turns spaces
into their own tokens and silently desyncs the index/query token sets if
only one side sets it explicitly (copied from aj-krit/Project2/core/thai.py).
"""
from pythainlp.tokenize import word_tokenize


def normalize(s: str) -> str:
    return s.lower().strip()


def tok_word(s: str) -> list[str]:
    return word_tokenize(normalize(s), engine="newmm", keep_whitespace=False)


def tok_gram(s: str, n: int = 3) -> list[str]:
    s = "".join(normalize(s).split())
    if len(s) < n:
        return [s] if s else []
    return [s[i : i + n] for i in range(len(s) - n + 1)]
