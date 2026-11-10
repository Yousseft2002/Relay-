import re
import unicodedata


def slugify(value: str, max_length: int = 60) -> str:
    """Lowercase ASCII slug: 'Hello, World!' -> 'hello-world'."""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_length].rstrip("-")
