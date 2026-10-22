"""Extraction layer against cached LLM responses (no network).

The fixture cache in tests/fixtures/llm_cache holds the structured responses for one
sample case. The provider stub below raises if anything tries to reach the network,
so a prompt/schema change that invalidates the fixtures fails loudly instead of
silently calling the API. Regenerate with:

    LLM_CACHE_DIR=tests/fixtures/llm_cache uv run scripts/run_case.py --case-id case_00016 --compact
"""
from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

import pytest

from preop_triage.extract import extract_all
from preop_triage.llm import CachedLLM, LLMError
from preop_triage.pipeline import assemble_packet, build_case_facts

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CACHE = ROOT / "tests" / "fixtures" / "llm_cache"
CASE_ID = "case_00016"


class NoNetworkProvider:
    name = "fixture"

    def complete(self, **kwargs):
        raise LLMError(f"fixture cache miss for {kwargs.get('schema_name')}; regenerate tests/fixtures/llm_cache")


@pytest.fixture(scope="module")
def case():
    rows = [json.loads(l) for l in (ROOT / "data" / "patients_sample_50.jsonl").read_text().splitlines() if l.strip()]
    return next(r for r in rows if r["case_id"] == CASE_ID)


@pytest.fixture(scope="module")
def llm():
    assert FIXTURE_CACHE.exists() and any(FIXTURE_CACHE.glob("*.json")), "fixture cache missing"
    return CachedLLM(model="gpt-4.1-mini", provider=NoNetworkProvider(), cache_dir=FIXTURE_CACHE, use_cache=True)


def test_extraction_from_fixtures_reads_the_record(case, llm):
    sub = case["submission"]
    exs = extract_all(llm, sub["documents"], sub["procedure"]["procedure_type"])
    assert llm.stats.calls == 0 and llm.stats.failures == 0, llm.stats.errors
    assert all(ex.facts is not None for ex in exs)

    facts = build_case_facts(sub, exs)
    # The nursing note's 08:06 reading and the 08:30 addendum recheck are both extracted, with times.
    text_bps = sorted((r.clock, r.systolic, r.diastolic) for r in facts.readings if r.kind == "BP" and r.source == "document")
    assert (time(8, 6), 189.0, 112.0) in text_bps and (time(8, 30), 137.0, 78.0) in text_bps
    # Celsius temperature converted.
    assert any(r.kind == "TEMP" and r.source == "document" and abs(r.temp_f - 98.78) < 0.01 for r in facts.readings)
    # Documentation facts.
    assert any(h.day == date(2026, 2, 21) and h.verified for h in facts.hps)
    assert any(c.status == "SIGNED" and c.verified for c in facts.consents)
    # Aspirin is not an anticoagulant.
    assert facts.drugs == []
    # Every extracted quote that drives a decision was verified against the document text.
    for r in facts.readings:
        assert r.verified


def test_fixture_decision_matches_label(case, llm):
    sub = case["submission"]
    exs = extract_all(llm, sub["documents"], sub["procedure"]["procedure_type"])
    packet = assemble_packet(sub, build_case_facts(sub, exs), exs, llm)
    assert packet.decision == case["label"]["decision"] == "READY"
    assert [i.category for i in packet.issues] == case["label"]["categories"] == []
    bp = next(c for c in packet.checks if c.name == "Blood pressure exclusion")
    assert bp.status == "PASS" and bp.inputs["systolic"] == 137.0 and bp.inputs["latest_time"] == "08:30"


def test_llm_failure_degrades_to_unknown_not_ready(case):
    """Fail-safe (A17): with no cache and a failing provider, every document is 'unknown' and the case is NEEDS_FOLLOW_UP."""
    sub = case["submission"]
    llm = CachedLLM(model="gpt-4.1-mini", provider=NoNetworkProvider(), cache_dir=ROOT / "tests" / "fixtures" / "empty_cache", use_cache=False)
    exs = extract_all(llm, sub["documents"], sub["procedure"]["procedure_type"])
    packet = assemble_packet(sub, build_case_facts(sub, exs), exs, llm)
    assert packet.decision == "NEEDS_FOLLOW_UP"
    assert "MISSING_REQUIRED_DATA" in {i.category for i in packet.issues}
    assert packet.meta.llm_failures == len(sub["documents"]) or packet.meta.llm_failures > 0
    assert len(packet.meta.documents_failed) == len(sub["documents"])
