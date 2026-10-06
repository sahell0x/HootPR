def sync_all(limit: int) -> list[str]:
    """Synchronize up to `limit` items and return their names."""
    return [f"item-{i}" for i in range(limit)]
