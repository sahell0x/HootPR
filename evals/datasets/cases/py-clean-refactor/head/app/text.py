def slugify(value: str) -> str:
    """Lowercase ``value`` and replace every non-alphanumeric character with a dash."""
    text = value.strip().lower()
    out = ""
    for ch in text:
        out += ch if ch.isalnum() else "-"
    return out
