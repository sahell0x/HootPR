def slugify(value):
    value = value.strip().lower()
    out = ""
    for ch in value:
        if ch.isalnum():
            out += ch
        else:
            out += "-"
    return out
