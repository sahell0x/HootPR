def paginate(items: list, page: int, size: int) -> list:
    start = page * size
    return items[start:start + size]
