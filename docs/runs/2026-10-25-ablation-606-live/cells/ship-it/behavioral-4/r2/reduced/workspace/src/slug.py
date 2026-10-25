import unicodedata


def slugify(text):
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "-".join(stripped.lower().split())
