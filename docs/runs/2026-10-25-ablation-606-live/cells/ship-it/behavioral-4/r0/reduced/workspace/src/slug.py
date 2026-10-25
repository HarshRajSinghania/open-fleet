import unicodedata


def slugify(text):
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "-".join(ascii_text.lower().split())
