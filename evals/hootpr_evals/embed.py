"""Deterministic hashing embedder for fake-LLM learnings runs (no keys, no network).

Bag of lowercase word tokens hashed into `dims` buckets and L2-normalized: texts that share words
get a positive cosine, texts that share none get 0. It checks the retrieval plumbing, not retrieval
quality (real runs use the `embed` role through LLMGateway)."""

from __future__ import annotations

import hashlib
import math
import re

TOKEN_RE = re.compile(r"[a-z0-9_]+")
MIN_TOKEN_LEN = 3
STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "any",
        "can",
        "had",
        "her",
        "was",
        "one",
        "our",
        "out",
        "has",
        "him",
        "his",
        "how",
        "its",
        "may",
        "new",
        "now",
        "see",
        "who",
        "did",
        "get",
        "let",
        "say",
        "she",
        "too",
        "use",
        "that",
        "this",
        "with",
        "from",
        "they",
        "will",
        "what",
        "when",
        "your",
        "have",
        "were",
        "been",
        "into",
        "than",
        "then",
        "them",
        "there",
        "their",
        "these",
        "those",
        "which",
        "while",
        "would",
        "should",
        "could",
        "about",
        "also",
        "only",
        "just",
        "some",
        "such",
        "over",
        "each",
        "other",
        "does",
        "don",
    }
)


def _tokens(text: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) >= MIN_TOKEN_LEN and t not in STOPWORDS]


def _bucket(token: str, dims: int) -> int:
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big") % dims


def hash_embed(texts: list[str], dims: int = 64) -> list[list[float]]:
    out: list[list[float]] = []
    for text in texts:
        vec = [0.0] * dims
        for tok in _tokens(text):
            vec[_bucket(tok, dims)] += 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        out.append([x / norm for x in vec] if norm else vec)
    return out
