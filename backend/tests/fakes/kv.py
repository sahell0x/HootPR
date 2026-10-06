class DictKV:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.data: dict[str, str] = dict(initial or {})
        self.ttls: dict[str, int | None] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value
        self.ttls[key] = ex

    def delete(self, key: str) -> None:
        self.data.pop(key, None)
