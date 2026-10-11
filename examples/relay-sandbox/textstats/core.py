"""Core text statistics."""
from __future__ import annotations

import re

WORD = re.compile(r"[A-Za-z0-9']+")


def word_count(text: str) -> int:
    """Number of words in `text`. Words are runs of letters, digits or apostrophes."""
    return len(WORD.findall(text))
