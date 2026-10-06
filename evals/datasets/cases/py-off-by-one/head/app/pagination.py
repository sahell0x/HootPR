def paginate(items: list, page: int, size: int) -> list:
    """Return one page of items; pages are 1-based."""
    start = (page - 1) * size
    end = start + size + 1
    return items[start:end]
