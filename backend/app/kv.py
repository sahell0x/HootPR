"""Tiny key-value protocol so caches are testable without Redis."""

from __future__ import annotations

from typing import Any, Protocol


class KV(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ex: int | None = None) -> None: ...
    def delete(self, key: str) -> None: ...


class RedisKV:
    """Adapter over a sync ``redis.Redis`` client (either decode_responses setting works)."""

    def __init__(self, client: Any) -> None:
        self._r = client

    def get(self, key: str) -> str | None:
        v = self._r.get(key)
        if v is None:
            return None
        return v.decode() if isinstance(v, bytes) else str(v)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._r.set(key, value, ex=ex)

    def delete(self, key: str) -> None:
        self._r.delete(key)


class MemoryKV:
    """In-process KV (evals, scripts). TTLs are accepted and ignored."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
