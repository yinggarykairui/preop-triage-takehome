"""Evidence verification: every LLM quote must be a real substring of its document.

This is the anti-hallucination guard (A17). A quote that cannot be found makes the
fact unverified; unverified facts can only ever weaken a decision.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return _WS.sub(" ", s).strip()


def quote_in_text(quote: str | None, text: str | None) -> bool:
    """Exact or whitespace/unicode-normalized substring match. Empty quotes never verify."""
    if not quote or not text:
        return False
    if quote in text:
        return True
    return normalize_text(quote) in normalize_text(text)
