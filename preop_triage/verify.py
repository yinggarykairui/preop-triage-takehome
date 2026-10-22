"""Evidence verification: every LLM quote must be a real substring of its document.

This is the anti-hallucination guard (A17). A quote that cannot be found makes the
fact unverified; unverified facts can only ever weaken a decision.

Matching tiers (each strictly about formatting, never about content):
  1. exact substring
  2. normalized: NFKC, straight quotes, control chars and degree signs removed, whitespace collapsed
  3. punctuation-insensitive: only letters, digits, '.', '%' and '/' are compared, so numbers,
     units and ratios like 189/112 must still match exactly
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_DEGREE = re.compile("[°º˚⁰]")
_PUNCT = re.compile(r"[^0-9A-Za-z.%/]+")
_MOJIBAKE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]\S?")


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    # A control character in an LLM quote is mojibake for a multi-byte symbol (seen: "\x176F" for "°F");
    # drop it together with the one character it garbled, then any remaining control characters.
    s = _MOJIBAKE.sub("", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))
    s = _DEGREE.sub("", s)
    return _WS.sub(" ", s).strip()


def _loose(s: str) -> str:
    return _WS.sub(" ", _PUNCT.sub(" ", normalize_text(s))).strip()


def quote_in_text(quote: str | None, text: str | None) -> bool:
    """Exact, normalized, or punctuation-insensitive substring match. Empty quotes never verify."""
    if not quote or not text:
        return False
    if quote in text:
        return True
    nq, nt = normalize_text(quote), normalize_text(text)
    if nq and nq in nt:
        return True
    lq = _loose(quote)
    return bool(lq) and lq in _loose(text)
