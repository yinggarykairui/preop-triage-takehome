"""Runtime switches used only by the ablation study (`make ablation`).

TRIAGE_ABLATE is a comma-separated list; the production defaults are all on:
  no_verify    - accept every LLM quote without checking it against the document (A17 off, part 1)
  no_failsafe  - UNKNOWN checks no longer block clearance or produce MISSING_REQUIRED_DATA issues (A17 off, part 2)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

VALID_ABLATIONS = {"no_verify", "no_failsafe"}


@dataclass(frozen=True)
class Settings:
    verify_quotes: bool = True
    fail_safe: bool = True

    @property
    def ablations(self) -> list[str]:
        out = []
        if not self.verify_quotes:
            out.append("no_verify")
        if not self.fail_safe:
            out.append("no_failsafe")
        return out


def settings() -> Settings:
    """Read TRIAGE_ABLATE from the environment (re-read on every call so a runner can switch variants in-process)."""
    raw = {s.strip().lower() for s in os.environ.get("TRIAGE_ABLATE", "").split(",") if s.strip()}
    unknown = raw - VALID_ABLATIONS
    if unknown:
        raise ValueError(f"unknown TRIAGE_ABLATE value(s) {sorted(unknown)}; valid: {sorted(VALID_ABLATIONS)}")
    return Settings(verify_quotes="no_verify" not in raw, fail_safe="no_failsafe" not in raw)
