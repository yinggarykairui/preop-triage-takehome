"""Code-only normalization: dates, units, lab and drug canonicalization.

No LLM calls here. Everything is deterministic and unit-tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

# ---------------------------------------------------------------------------
# Dates (A1)
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})"), lambda m: date(int(m[1]), int(m[2]), int(m[3]))),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})"), lambda m: date(int(m[3]), int(m[1]), int(m[2]))),
]


def parse_date(value: str | None) -> date | None:
    """Parse 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SSZ' or 'MM/DD/YYYY' to a UTC calendar date."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    for pat, build in _DATE_PATTERNS:
        m = pat.match(v)
        if m:
            try:
                return build(m)
            except ValueError:
                return None
    return None


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO timestamp to an aware UTC datetime; date-only strings get no time."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_clock_time(value: str | None) -> time | None:
    """'08:30' / '8:30' / '08:30:15' -> time, else None."""
    if not value or not isinstance(value, str):
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$", value)
    if not m:
        return None
    try:
        return time(int(m[1]), int(m[2]), int(m[3] or 0))
    except ValueError:
        return None


def days_between(later: date, earlier: date) -> int:
    return (later - earlier).days


def within_window(procedure_date: date, item_date: date, max_days: int) -> bool:
    """A2/A3: inclusive window, items after the procedure date never qualify."""
    delta = days_between(procedure_date, item_date)
    return 0 <= delta <= max_days


# ---------------------------------------------------------------------------
# Units (A10)
# ---------------------------------------------------------------------------


def celsius_to_fahrenheit(c: float) -> float:
    return round(c * 9.0 / 5.0 + 32.0, 2)


def temperature_to_f(value: float, unit: str | None) -> float:
    u = (unit or "F").strip().upper().replace("°", "")
    if u.startswith("C"):
        return celsius_to_fahrenheit(value)
    return round(float(value), 2)


# ---------------------------------------------------------------------------
# Labs (A11)
# ---------------------------------------------------------------------------

LAB_STATUS_COUNTS = {"final", "corrected", "amended"}


def canonical_lab(code: str | None, display: str | None) -> str | None:
    """Return 'CBC', 'CMP', 'BMP' or None, using both code and display text."""
    c = (code or "").strip().upper()
    d = (display or "").strip().lower()
    c_core = re.sub(r"^(LAB|LOINC)[-_ ]", "", c)
    d_compact = re.sub(r"[^a-z]", "", d)
    # BMP must be decided before CMP: 'metabolic panel' appears in both.
    if c_core == "BMP" or "basicmetabolic" in d_compact or re.search(r"\bbmp\b", d):
        return "BMP"
    if c_core == "CMP" or "comprehensivemetabolic" in d_compact or re.search(r"\bcmp\b", d):
        return "CMP"
    if c_core == "CBC" or "completebloodcount" in d_compact or re.search(r"\bcbc\b", d) or "hemogram" in d:
        return "CBC"
    return None


def lab_status_counts(status: str | None) -> bool:
    return (status or "").strip().lower() in LAB_STATUS_COUNTS


# ---------------------------------------------------------------------------
# Drugs (A14)
# ---------------------------------------------------------------------------

# brand / alias -> generic
ANTICOAGULANT_ALIASES: dict[str, str] = {
    "warfarin": "warfarin", "coumadin": "warfarin", "jantoven": "warfarin",
    "apixaban": "apixaban", "eliquis": "apixaban",
    "rivaroxaban": "rivaroxaban", "xarelto": "rivaroxaban",
    "dabigatran": "dabigatran", "pradaxa": "dabigatran",
    "edoxaban": "edoxaban", "savaysa": "edoxaban", "lixiana": "edoxaban",
    "betrixaban": "betrixaban", "bevyxxa": "betrixaban",
    "enoxaparin": "enoxaparin", "lovenox": "enoxaparin",
    "dalteparin": "dalteparin", "fragmin": "dalteparin",
    "fondaparinux": "fondaparinux", "arixtra": "fondaparinux",
    "heparin": "heparin",
}

ANTIPLATELET_ALIASES: set[str] = {
    "aspirin", "asa", "ecotrin", "clopidogrel", "plavix", "ticagrelor", "brilinta",
    "prasugrel", "effient", "dipyridamole", "aggrenox", "ticlopidine",
}

_WORD = re.compile(r"[a-z]+")


def canonical_anticoagulant(name: str | None) -> str | None:
    """Map a free-text drug string to a generic anticoagulant name, or None."""
    if not name:
        return None
    for w in _WORD.findall(name.lower()):
        if w in ANTICOAGULANT_ALIASES:
            return ANTICOAGULANT_ALIASES[w]
    return None


def is_antiplatelet(name: str | None) -> bool:
    if not name:
        return False
    return any(w in ANTIPLATELET_ALIASES for w in _WORD.findall(name.lower()))


ANTICOAG_TEXT_HINT = re.compile(
    r"\b(" + "|".join(sorted(ANTICOAGULANT_ALIASES)) + r"|anticoag\w*|blood thinner\w*|doac|bridg\w*|inr)\b",
    re.I,
)


def mentions_anticoagulation(text: str | None) -> bool:
    """Cheap code-side prefilter for the anticoagulation extractor."""
    return bool(text) and bool(ANTICOAG_TEXT_HINT.search(text))


# ---------------------------------------------------------------------------
# Readings (A7, A8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """One vital reading from any source, normalized."""

    kind: str  # 'BP' | 'TEMP'
    day: date
    clock: time | None
    systolic: float | None = None
    diastolic: float | None = None
    temp_f: float | None = None
    source: str = ""  # e.g. 'vitals[2]' or 'document'
    doc_id: str | None = None
    doc_type: str | None = None
    quote: str | None = None
    verified: bool = True

    def abnormality(self) -> tuple:
        """Sort key: higher = more abnormal. Used only for tie-breaks (A8)."""
        if self.kind == "BP":
            s, d = self.systolic or 0.0, self.diastolic or 0.0
            return (int(s >= 180 or d >= 110), s, d)
        return (int((self.temp_f or 0.0) > 100.4), self.temp_f or 0.0)


def most_recent_reading(readings: list[Reading]) -> Reading | None:
    """A8: latest by date, then time; unresolved ties go to the more abnormal reading."""
    if not readings:
        return None
    latest_day = max(r.day for r in readings)
    same_day = [r for r in readings if r.day == latest_day]
    if any(r.clock is None for r in same_day):
        tied = same_day
    else:
        latest_clock = max(r.clock for r in same_day)  # type: ignore[type-var]
        tied = [r for r in same_day if r.clock == latest_clock]
    return max(tied, key=lambda r: r.abnormality())
