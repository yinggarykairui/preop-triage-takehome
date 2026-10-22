"""Ablation switches and the perturbation generator (no network; extraction replays the cache)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from preop_triage.config import Settings, settings
from preop_triage.rules import build_issues, decide
from preop_triage.schemas import Check

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import perturb  # noqa: E402


def _unknown() -> Check:
    return Check(
        rule="RULE_4",
        name="Temperature exclusion",
        status="UNKNOWN",
        category="ACUTE_SAFETY_EXCLUSION",
        summary="no reading",
        unknown_key="temperature",
    )


def _pass() -> Check:
    return Check(
        rule="RULE_1", name="Signed surgical consent", status="PASS", category="REQUIRED_DOCUMENTATION", summary="ok"
    )


def test_settings_default_and_parsing(monkeypatch):
    monkeypatch.delenv("TRIAGE_ABLATE", raising=False)
    assert settings() == Settings(True, True) and settings().ablations == []
    monkeypatch.setenv("TRIAGE_ABLATE", "no_verify, no_failsafe")
    assert settings() == Settings(False, False)
    monkeypatch.setenv("TRIAGE_ABLATE", "bogus")
    with pytest.raises(ValueError):
        settings()


def test_fail_safe_flag_controls_unknown_handling(monkeypatch):
    monkeypatch.delenv("TRIAGE_ABLATE", raising=False)
    checks = [_pass(), _unknown()]
    assert decide(checks)[0] == "NEEDS_FOLLOW_UP" and [i.category for i in build_issues(checks)] == [
        "MISSING_REQUIRED_DATA"
    ]
    assert decide(checks, fail_safe=False)[0] == "READY" and build_issues(checks, fail_safe=False) == []
    monkeypatch.setenv("TRIAGE_ABLATE", "no_failsafe")
    assert decide(checks)[0] == "READY"


def test_shift_iso_keeps_format():
    assert perturb.shift_iso("2026-03-01", 30) == "2026-03-31"
    assert perturb.shift_iso("2026-02-27T09:05:00Z", 2) == "2026-03-01T09:05:00Z"
    assert perturb.shift_iso(None, 5) is None


def test_swap_brand_generic():
    assert perturb.swap_brand_generic("warfarin (Coumadin) 5 mg PO daily") == "Coumadin 5 mg PO daily"
    assert (
        perturb.swap_brand_generic("Xarelto 20 mg PO daily with evening meal")
        == "rivaroxaban 20 mg PO daily with evening meal"
    )
    assert perturb.swap_brand_generic("ASA 81 mg PO daily") is None


@pytest.fixture(scope="module")
def mutations():
    bases = perturb.load_bases(ROOT / "data" / "patients_sample_50.jsonl", perturb.DEFAULT_MODEL)
    return perturb.generate(bases, seed=0, max_per_family=2)


def test_generator_is_seeded_and_well_formed(mutations):
    assert {m.family for m in mutations} == set(perturb.FAMILIES)
    for m in mutations:
        assert m.expected_decision in {"READY", "NEEDS_FOLLOW_UP", "NOT_CLEARED"}
        assert m.expected_categories == sorted(m.expected_categories)
        assert (m.expected_decision == "READY") == (m.expected_categories == [])
    bases = perturb.load_bases(ROOT / "data" / "patients_sample_50.jsonl", perturb.DEFAULT_MODEL)
    again = perturb.generate(bases, seed=0, max_per_family=2)
    assert [(m.family, m.name, m.base_case) for m in again] == [(m.family, m.name, m.base_case) for m in mutations]


def test_structured_mutations_never_touch_documents(mutations):
    import json

    rows = {
        json.loads(line)["case_id"]: json.loads(line)["submission"]
        for line in (ROOT / "data" / "patients_sample_50.jsonl").read_text().splitlines()
        if line.strip()
    }
    for m in mutations:
        same_docs = m.submission["documents"] == rows[m.base_case]["documents"]
        assert same_docs == (not m.needs_llm), (m.family, m.name)
