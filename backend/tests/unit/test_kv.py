from typing import Any

from app.kv import RedisKV


class _StubRedis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.ex: dict[str, int | None] = {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value.encode()  # like a decode_responses=False client
        self.ex[key] = ex

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


def test_redis_kv_round_trip_decodes_bytes() -> None:
    stub = _StubRedis()
    kv = RedisKV(stub)
    kv.set("k", "v", ex=10)
    assert kv.get("k") == "v" and stub.ex["k"] == 10
    kv.delete("k")
    assert kv.get("k") is None


def test_memory_kv_roundtrip() -> None:
    from app.kv import MemoryKV

    kv = MemoryKV()
    assert kv.get("a") is None
    kv.set("a", "1", ex=10)
    assert kv.get("a") == "1"
    kv.delete("a")
    assert kv.get("a") is None
    kv.delete("missing")
