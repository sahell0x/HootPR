"""Deterministic 'embeddings': one dimension per vocabulary word (+ a small bias)."""

VOCAB = ("print", "logging", "sql", "auth", "test", "docstring", "type", "async", "secret")


def keyword_vector(text: str) -> list[float]:
    low = text.lower()
    return [1.0 if w in low else 0.0 for w in VOCAB] + [0.05]


def keyword_embed(texts: list[str]) -> list[list[float]]:
    return [keyword_vector(t) for t in texts]
