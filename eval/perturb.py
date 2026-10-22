#!/usr/bin/env python3
"""Perturbation suite: seeded mutations of sample records whose correct answer follows by construction.

Each family takes base cases that satisfy a precondition (checked on the base case's extracted
facts, which replay from the committed LLM cache) and applies a mutation whose effect on the
decision and issue categories is known from the policy alone. Structured-field mutations never
change document text, so the extraction cache still hits and they run without an API key.
Text mutations (`needs_llm`) change a document; their responses are cached on first run so a
reviewer can replay them without a key.

    uv run eval/perturb.py                 # -> results/perturbation.md + .json
    uv run eval/perturb.py --list          # families, base counts, mutation counts
    make perturb

Families (see FAMILIES for the one-line description of each):
  hp_window, cbc_window, cmp_window, lab_entered_in_error, risk_upgrade,
  bp_threshold, temp_threshold_f, temp_threshold_c, bp_recheck,
  anticoag_brand_generic, anticoag_wrong_drug, plan_no_postop (LLM),
  consent_pending (LLM), temp_threshold_c_text (LLM),
  null_procedure_date, missing_risk
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import triage_submission  # noqa: E402
from preop_triage.extract import DocExtraction, extract_all  # noqa: E402
from preop_triage.llm import CachedLLM  # noqa: E402
from preop_triage.normalize import ANTICOAGULANT_ALIASES, canonical_anticoagulant, parse_date  # noqa: E402
from preop_triage.pipeline import assemble_packet, build_case_facts  # noqa: E402
from preop_triage.rules import CaseFacts  # noqa: E402
from preop_triage.schemas import TriagePacket  # noqa: E402

DEFAULT_MODEL = "gpt-4.1-mini"
NFU, READY, NC = "NEEDS_FOLLOW_UP", "READY", "NOT_CLEARED"
DOC, TEST, AC, SAFE, MISSING = (
    "REQUIRED_DOCUMENTATION",
    "REQUIRED_TESTING",
    "ANTICOAGULATION_MANAGEMENT",
    "ACUTE_SAFETY_EXCLUSION",
    "MISSING_REQUIRED_DATA",
)

FAMILIES: dict[str, str] = {
    "hp_window": "H&P exactly 30 days before the procedure (PASS) vs 31 (FAIL); procedure date, labs, vitals shifted together",
    "cbc_window": "single CBC at day 30/31 (LOW, MODERATE) or 14/15 (HIGH)",
    "cmp_window": "risk set to HIGH with CBC in window; single CMP at day 14 vs 15",
    "lab_entered_in_error": "a newer entered-in-error CBC is added; the older final CBC must still be used",
    "risk_upgrade": "LOW/MODERATE case with CBC 15-30 days out becomes HIGH -> CBC outside 14-day window",
    "bp_threshold": "most recent BP 179/100 vs 180/100 and 150/109 vs 150/110 (structured)",
    "temp_threshold_f": "most recent temperature 100.4 F vs 100.5 F (structured)",
    "temp_threshold_c": "most recent temperature 38.0 C (=100.4 F) vs 38.1 C (=100.58 F) (structured value_c)",
    "bp_recheck": "abnormal BP followed by an in-range recheck (READY) and the reverse (NOT_CLEARED); list order varied",
    "anticoag_brand_generic": "medication-list name swapped brand<->generic; outcome must not change",
    "anticoag_wrong_drug": "medication-list anticoagulant replaced by a different one the plan does not name",
    "plan_no_postop": "[LLM] the plan's post-op instruction replaced by a deferral to the surgical team",
    "consent_pending": "[LLM] the signed consent's signature line replaced by 'Patient signature: pending'",
    "temp_threshold_c_text": "[LLM] a nursing addendum with 38.0 C vs 38.1 C appended to the latest document",
    "null_procedure_date": "structured procedure_date removed; every document that states a date agrees with it (A4 fallback)",
    "missing_risk": "procedure_risk removed, with and without any CBC on file (A5)",
}

BRAND_FOR: dict[str, str] = {
    "warfarin": "Coumadin",
    "apixaban": "Eliquis",
    "rivaroxaban": "Xarelto",
    "dabigatran": "Pradaxa",
    "edoxaban": "Savaysa",
    "enoxaparin": "Lovenox",
    "dalteparin": "Fragmin",
    "fondaparinux": "Arixtra",
}


@dataclass
class Mutation:
    family: str
    name: str
    base_case: str
    expected_decision: str
    expected_categories: list[str]
    needs_llm: bool
    rationale: str
    submission: dict = field(repr=False)


@dataclass
class Base:
    case_id: str
    sub: dict
    facts: CaseFacts
    exs: list[DocExtraction]
    packet: TriagePacket
    label: dict

    @property
    def pd(self) -> date | None:
        return self.facts.procedure_date

    @property
    def review_day(self) -> date:
        return parse_date((self.sub.get("metadata") or {}).get("submission_received_at")) or self.pd or date(2026, 1, 1)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def shift_iso(value: str | None, days: int) -> str | None:
    """Shift the calendar part of 'YYYY-MM-DD[THH:MM:SSZ]' by `days`, keeping the format."""
    if not value:
        return value
    d = date.fromisoformat(value[:10]) + timedelta(days=days)
    return d.isoformat() + value[10:]


def iso_at(d: date, hhmm: str = "10:00") -> str:
    return f"{d.isoformat()}T{hhmm}:00Z"


def lab_entries(sub: dict, canonical: str, facts: CaseFacts) -> list[int]:
    return [i for i, lab in enumerate(facts.labs) if lab.canonical == canonical]


def latest_lab_delta(base: Base, canonical: str) -> int | None:
    items = [lab for lab in base.facts.labs if lab.canonical == canonical and lab.counts and lab.day]
    if not items or not base.pd:
        return None
    return (base.pd - max(lab.day for lab in items)).days


def keep_single_lab(sub: dict, facts: CaseFacts, canonical: str, day: date, code: str) -> dict:
    """Drop every lab of this canonical type and add one final result on `day`."""
    out = copy.deepcopy(sub)
    drop = set(lab_entries(sub, canonical, facts))
    out["labs"] = [lab for i, lab in enumerate(sub["labs"]) if i not in drop]
    out["labs"].append(
        {
            "id": f"perturb-{canonical.lower()}",
            "code": code,
            "display": {"CBC": "Complete Blood Count", "CMP": "Comprehensive Metabolic Panel"}[canonical],
            "effective_at": iso_at(day),
            "status": "final",
            "source": "Perturbation",
        }
    )
    return out


def add_vital(sub: dict, vital: dict, position: str = "end") -> dict:
    out = copy.deepcopy(sub)
    vitals = list(out.get("vitals") or [])
    vitals.insert(0, vital) if position == "start" else vitals.append(vital)
    out["vitals"] = vitals
    return out


def bp(day: date, hhmm: str, s: int, d: int) -> dict:
    return {
        "type": "blood_pressure",
        "systolic": s,
        "diastolic": d,
        "date": iso_at(day, hhmm),
        "source": "Perturbation",
    }


def all_readings_normal(base: Base) -> bool:
    return all(r.abnormality()[0] == 0 for r in base.facts.readings if r.verified)


def no_untimed_reading_on(base: Base, day: date) -> bool:
    return not any(r.verified and r.day == day and r.clock is None for r in base.facts.readings)


def is_ready(base: Base) -> bool:
    return base.packet.decision == READY and base.pd is not None


def swap_brand_generic(name: str) -> str | None:
    """'warfarin (Coumadin) 5 mg PO daily' -> 'Coumadin 5 mg PO daily'; 'Xarelto 20 mg' -> 'rivaroxaban 20 mg'."""
    g = canonical_anticoagulant(name)
    if not g or g not in BRAND_FOR:
        return None
    words = re.findall(r"[A-Za-z]+", name)
    written = next(w for w in words if w.lower() in ANTICOAGULANT_ALIASES)
    new = BRAND_FOR[g] if written.lower() == g else g
    rest = re.sub(
        r"\(\s*\)", "", re.sub(r"\b(" + "|".join(map(re.escape, ANTICOAGULANT_ALIASES)) + r")\b", "", name, flags=re.I)
    )
    rest = re.sub(r"\s+", " ", rest).strip(" ,")
    return f"{new} {rest}".strip()


def pick(rng: random.Random, items: list, k: int) -> list:
    items = sorted(items, key=lambda b: b.case_id)
    return items if len(items) <= k else rng.sample(items, k)


# ---------------------------------------------------------------------------
# families
# ---------------------------------------------------------------------------


def fam_hp_window(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = [b for b in bases if is_ready(b) and all_readings_normal(b) and b.facts.hps]
    for b in pick(rng, eligible, k):
        hp_day = max(h.day for h in b.facts.hps if h.verified)
        delta = (b.pd - hp_day).days
        for target, dec, cats in ((30, READY, []), (31, NFU, [DOC])):
            shift = target - delta
            sub = copy.deepcopy(b.sub)
            sub["procedure"]["procedure_date"] = shift_iso(sub["procedure"]["procedure_date"], shift)
            sub["metadata"]["submission_received_at"] = shift_iso(sub["metadata"]["submission_received_at"], shift)
            for lab in sub["labs"]:
                lab["effective_at"] = shift_iso(lab["effective_at"], shift)
            for v in sub.get("vitals") or []:
                v["date"] = shift_iso(v["date"], shift)
            out.append(
                Mutation(
                    "hp_window",
                    f"hp_day_{target}",
                    b.case_id,
                    dec,
                    cats,
                    False,
                    f"H&P {hp_day} is {target} days before the shifted procedure date; labs/vitals shifted by {shift:+d} days",
                    sub,
                )
            )
    return out


def fam_cbc_window(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    for b in pick(rng, [b for b in bases if is_ready(b)], k):
        window = 14 if b.sub["procedure"]["procedure_risk"] == "HIGH" else 30
        for target, dec, cats in ((window, READY, []), (window + 1, NFU, [TEST])):
            sub = keep_single_lab(b.sub, b.facts, "CBC", b.pd - timedelta(days=target), "CBC")
            out.append(
                Mutation(
                    "cbc_window",
                    f"cbc_day_{target}_{b.sub['procedure']['procedure_risk'].lower()}",
                    b.case_id,
                    dec,
                    cats,
                    False,
                    f"only CBC is {target} days before the procedure (limit {window})",
                    sub,
                )
            )
    return out


def fam_cmp_window(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = [b for b in bases if is_ready(b) and (latest_lab_delta(b, "CBC") or 99) <= 14]
    for b in pick(rng, eligible, k):
        for target, dec, cats in ((14, READY, []), (15, NFU, [TEST])):
            sub = keep_single_lab(b.sub, b.facts, "CMP", b.pd - timedelta(days=target), "CMP")
            sub["procedure"]["procedure_risk"] = "HIGH"
            out.append(
                Mutation(
                    "cmp_window",
                    f"cmp_day_{target}_high",
                    b.case_id,
                    dec,
                    cats,
                    False,
                    f"risk HIGH, CBC {latest_lab_delta(b, 'CBC')} days out, only CMP is {target} days before the procedure (limit 14)",
                    sub,
                )
            )
    return out


def fam_lab_entered_in_error(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    for b in pick(rng, [b for b in bases if is_ready(b)], k):
        sub = copy.deepcopy(b.sub)
        sub["labs"].append(
            {
                "id": "perturb-eie",
                "code": "CBC",
                "display": "Complete Blood Count",
                "effective_at": iso_at(b.pd - timedelta(days=1)),
                "status": "entered-in-error",
                "source": "Perturbation",
            }
        )
        out.append(
            Mutation(
                "lab_entered_in_error",
                "newer_eie_cbc_ready",
                b.case_id,
                READY,
                [],
                False,
                "entered-in-error CBC at day 1 is skipped; the older final CBC still passes",
                sub,
            )
        )
        # and the same addition to a case whose only final CBC is pushed out of window: still fails
        sub2 = keep_single_lab(sub, b.facts, "CBC", b.pd - timedelta(days=40), "CBC")
        sub2["labs"].append(copy.deepcopy(sub["labs"][-1]))
        out.append(
            Mutation(
                "lab_entered_in_error",
                "newer_eie_cbc_still_fails",
                b.case_id,
                NFU,
                [TEST],
                False,
                "entered-in-error CBC at day 1 must not rescue a final CBC at day 40",
                sub2,
            )
        )
    return out


def fam_risk_upgrade(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = [
        b
        for b in bases
        if is_ready(b)
        and b.sub["procedure"]["procedure_risk"] in ("LOW", "MODERATE")
        and 15 <= (latest_lab_delta(b, "CBC") or 0) <= 30
    ]
    for b in pick(rng, eligible, k):
        sub = copy.deepcopy(b.sub)
        sub["procedure"]["procedure_risk"] = "HIGH"
        out.append(
            Mutation(
                "risk_upgrade",
                "low_to_high_cbc_out_of_14",
                b.case_id,
                NFU,
                [TEST],
                False,
                f"CBC {latest_lab_delta(b, 'CBC')} days out passes at 30 but not at 14",
                sub,
            )
        )
    return out


def _vital_bases(bases: list[Base]) -> list[Base]:
    return [b for b in bases if is_ready(b) and all_readings_normal(b)]


def fam_bp_threshold(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    for b in pick(rng, _vital_bases(bases), k):
        day = b.review_day
        for s, d, dec, cats in (
            (179, 100, READY, []),
            (180, 100, NC, [SAFE]),
            (150, 109, READY, []),
            (150, 110, NC, [SAFE]),
        ):
            out.append(
                Mutation(
                    "bp_threshold",
                    f"bp_{s}_{d}",
                    b.case_id,
                    dec,
                    cats,
                    False,
                    f"new most recent BP {s}/{d} at {day} 23:50",
                    add_vital(b.sub, bp(day, "23:50", s, d)),
                )
            )
    return out


def fam_temp_threshold_f(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    for b in pick(rng, _vital_bases(bases), k):
        day = b.review_day
        for t, dec, cats in ((100.4, READY, []), (100.5, NC, [SAFE])):
            v = {"type": "temperature", "value_f": t, "date": iso_at(day, "23:50"), "source": "Perturbation"}
            out.append(
                Mutation(
                    "temp_threshold_f",
                    f"temp_{t}_f",
                    b.case_id,
                    dec,
                    cats,
                    False,
                    f"new most recent temperature {t} F",
                    add_vital(b.sub, v),
                )
            )
    return out


def fam_temp_threshold_c(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    for b in pick(rng, _vital_bases(bases), k):
        day = b.review_day
        for t, dec, cats in ((38.0, READY, []), (38.1, NC, [SAFE])):
            v = {"type": "temperature", "value_c": t, "date": iso_at(day, "23:50"), "source": "Perturbation"}
            out.append(
                Mutation(
                    "temp_threshold_c",
                    f"temp_{t}_c",
                    b.case_id,
                    dec,
                    cats,
                    False,
                    f"new most recent temperature {t} C (structured value_c)",
                    add_vital(b.sub, v),
                )
            )
    return out


def fam_bp_recheck(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = [b for b in _vital_bases(bases) if no_untimed_reading_on(b, b.review_day)]
    for b in pick(rng, eligible, k):
        day = b.review_day
        high, ok = bp(day, "23:40", 185, 95), bp(day, "23:50", 128, 78)
        out.append(
            Mutation(
                "bp_recheck",
                "abnormal_then_recheck_ok",
                b.case_id,
                READY,
                [],
                False,
                "185/95 at 23:40 then 128/78 at 23:50",
                add_vital(add_vital(b.sub, high), ok),
            )
        )
        out.append(
            Mutation(
                "bp_recheck",
                "abnormal_then_recheck_ok_reversed_list",
                b.case_id,
                READY,
                [],
                False,
                "same readings, later one listed first",
                add_vital(add_vital(b.sub, ok), high, "start"),
            )
        )
        high2, ok2 = bp(day, "23:50", 185, 95), bp(day, "23:40", 128, 78)
        out.append(
            Mutation(
                "bp_recheck",
                "ok_then_abnormal",
                b.case_id,
                NC,
                [SAFE],
                False,
                "128/78 at 23:40 then 185/95 at 23:50",
                add_vital(add_vital(b.sub, ok2), high2),
            )
        )
    return out


def fam_anticoag_brand_generic(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = [
        b for b in bases if any(swap_brand_generic(m.get("name")) for m in b.sub["medications"] if m.get("active"))
    ]
    for b in pick(rng, eligible, k):
        sub = copy.deepcopy(b.sub)
        swapped = []
        for m in sub["medications"]:
            new = swap_brand_generic(m.get("name")) if m.get("active") else None
            if new:
                swapped.append(f"{m['name']!r} -> {new!r}")
                m["name"] = new
        out.append(
            Mutation(
                "anticoag_brand_generic",
                "swap_name",
                b.case_id,
                b.label["decision"],
                sorted(b.label["categories"]),
                False,
                "; ".join(swapped) + " (outcome must equal the base label)",
                sub,
            )
        )
    return out


def fam_anticoag_wrong_drug(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = [
        b
        for b in bases
        if is_ready(b) and any(c.name.startswith("Plan for") and c.status == "PASS" for c in b.packet.checks)
    ]
    for b in pick(rng, eligible, k):
        sub = copy.deepcopy(b.sub)
        present = {canonical_anticoagulant(m.get("name")) for m in sub["medications"]} | {
            d.generic for d in b.facts.drugs
        }
        replacement = next(g for g in ("apixaban", "rivaroxaban", "warfarin", "dabigatran") if g not in present)
        for m in sub["medications"]:
            if m.get("active") and canonical_anticoagulant(m.get("name")):
                m["name"] = f"{replacement} 5 mg PO BID"
                break
        else:
            sub["medications"].append({"name": f"{replacement} 5 mg PO BID", "active": True})
        out.append(
            Mutation(
                "anticoag_wrong_drug",
                f"list_says_{replacement}",
                b.case_id,
                NFU,
                [AC],
                False,
                f"active anticoagulant on the list is now {replacement}, which no plan names",
                sub,
            )
        )
    return out


def fam_null_procedure_date(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = []
    for b in bases:
        if not is_ready(b):
            continue
        stated, tbd = set(), False
        for ex in b.exs:
            f = ex.facts
            if not f or not ex.verified(f.procedure_date.quote):
                continue
            if f.procedure_date.status == "DATE_STATED":
                d = parse_date(f.procedure_date.date)
                doc_day = parse_date(ex.doc_date)
                if d and not (doc_day and d < doc_day):
                    stated.add(d)
            elif f.procedure_date.status == "UNSCHEDULED_OR_TBD":
                tbd = True
        if stated == {b.pd} and not tbd:
            eligible.append(b)
    for b in pick(rng, eligible, k):
        sub = copy.deepcopy(b.sub)
        sub["procedure"]["procedure_date"] = None
        out.append(
            Mutation(
                "null_procedure_date",
                "date_only_in_text",
                b.case_id,
                READY,
                [],
                False,
                f"structured date removed; documents agree on {b.pd}",
                sub,
            )
        )
    return out


def fam_missing_risk(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    for b in pick(rng, [b for b in bases if is_ready(b) and b.sub["procedure"]["procedure_risk"]], k):
        sub = copy.deepcopy(b.sub)
        sub["procedure"]["procedure_risk"] = None
        out.append(
            Mutation(
                "missing_risk",
                "risk_null",
                b.case_id,
                NFU,
                [MISSING],
                False,
                "risk unknown; labs pass or are undecidable under some risk",
                sub,
            )
        )
        sub2 = copy.deepcopy(sub)
        sub2["labs"] = [lab for i, lab in enumerate(sub2["labs"]) if i not in set(lab_entries(sub2, "CBC", b.facts))]
        out.append(
            Mutation(
                "missing_risk",
                "risk_null_no_cbc",
                b.case_id,
                NFU,
                sorted([TEST, MISSING]),
                False,
                "risk unknown and no CBC at all: fails under every risk",
                sub2,
            )
        )
    return out


# --- text mutations (need the LLM; responses are cached) ---------------------


def _replace_in_doc(sub: dict, doc_id: str, old: str, new: str) -> dict | None:
    out = copy.deepcopy(sub)
    for d in out["documents"]:
        if d["doc_id"] == doc_id:
            if old not in d["text"]:
                return None
            d["text"] = d["text"].replace(old, new, 1)
            return out
    return None


def fam_consent_pending(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = [b for b in bases if is_ready(b) and sum(1 for c in b.facts.consents if c.status == "SIGNED") == 1]
    for b in pick(rng, eligible, k):
        c = next(c for c in b.facts.consents if c.status == "SIGNED")
        if not c.evidence.quote or c.evidence.quote not in next(
            d["text"] for d in b.sub["documents"] if d["doc_id"] == c.evidence.doc_id
        ):
            continue
        sub = _replace_in_doc(
            b.sub,
            c.evidence.doc_id,
            c.evidence.quote,
            "Patient signature: pending (to be signed on the day of surgery).",
        )
        if sub:
            out.append(
                Mutation(
                    "consent_pending",
                    "signature_line_pending",
                    b.case_id,
                    NFU,
                    [DOC],
                    True,
                    f"signature line {c.evidence.quote!r} replaced by a pending statement",
                    sub,
                )
            )
    return out


def fam_plan_no_postop(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = [b for b in bases if is_ready(b) and len(b.facts.plans) == 1 and b.facts.plans[0].post_op.evidence]
    for b in pick(rng, eligible, k):
        p = b.facts.plans[0]
        q = p.post_op.evidence.quote
        if not q or q not in next(d["text"] for d in b.sub["documents"] if d["doc_id"] == p.doc_evidence.doc_id):
            continue
        sub = _replace_in_doc(
            b.sub, p.doc_evidence.doc_id, q, "Post-operative resumption: to be determined by the surgical team."
        )
        if sub:
            out.append(
                Mutation(
                    "plan_no_postop",
                    "postop_deferred",
                    b.case_id,
                    NFU,
                    [AC],
                    True,
                    f"post-op instruction {q!r} replaced by a deferral",
                    sub,
                )
            )
    return out


def fam_temp_threshold_c_text(bases: list[Base], rng: random.Random, k: int) -> list[Mutation]:
    out = []
    eligible = []
    for b in _vital_bases(bases):
        latest_doc = max(b.sub["documents"], key=lambda d: d["date"])
        latest_reading = max((r.day for r in b.facts.readings if r.verified), default=date.min)
        if parse_date(latest_doc["date"]) and parse_date(latest_doc["date"]) >= latest_reading:
            eligible.append((b, latest_doc))
    latest_for = {b.case_id: doc for b, doc in eligible}
    for b in pick(rng, [e[0] for e in eligible], k):
        doc = latest_for[b.case_id]
        for t, dec, cats in ((38.0, READY, []), (38.1, NC, [SAFE])):
            sub = copy.deepcopy(b.sub)
            for d in sub["documents"]:
                if d["doc_id"] == doc["doc_id"]:
                    d["text"] = d["text"].rstrip() + f"\n\nADDENDUM 23:55: Temp {t} °C (oral) recheck by RN."
            out.append(
                Mutation(
                    "temp_threshold_c_text",
                    f"text_temp_{t}_c",
                    b.case_id,
                    dec,
                    cats,
                    True,
                    f"addendum 'Temp {t} °C' at 23:55 appended to the latest document ({doc['date']})",
                    sub,
                )
            )
    return out


GENERATORS = {
    "hp_window": fam_hp_window,
    "cbc_window": fam_cbc_window,
    "cmp_window": fam_cmp_window,
    "lab_entered_in_error": fam_lab_entered_in_error,
    "risk_upgrade": fam_risk_upgrade,
    "bp_threshold": fam_bp_threshold,
    "temp_threshold_f": fam_temp_threshold_f,
    "temp_threshold_c": fam_temp_threshold_c,
    "bp_recheck": fam_bp_recheck,
    "anticoag_brand_generic": fam_anticoag_brand_generic,
    "anticoag_wrong_drug": fam_anticoag_wrong_drug,
    "plan_no_postop": fam_plan_no_postop,
    "consent_pending": fam_consent_pending,
    "temp_threshold_c_text": fam_temp_threshold_c_text,
    "null_procedure_date": fam_null_procedure_date,
    "missing_risk": fam_missing_risk,
}
assert set(GENERATORS) == set(FAMILIES)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def load_bases(input_path: Path, model: str) -> list[Base]:
    rows = [json.loads(line) for line in input_path.read_text().splitlines() if line.strip()]
    llm = CachedLLM(model=model)
    bases = []
    for r in rows:
        sub = r["submission"]
        exs = extract_all(llm, sub["documents"], sub["procedure"]["procedure_type"])
        facts = build_case_facts(sub, exs)
        bases.append(Base(r["case_id"], sub, facts, exs, assemble_packet(sub, facts, exs, llm), r["label"]))
    return bases


def generate(bases: list[Base], seed: int = 0, max_per_family: int = 6) -> list[Mutation]:
    rng = random.Random(seed)
    out: list[Mutation] = []
    for gen in GENERATORS.values():
        out += gen(bases, random.Random(rng.random()), max_per_family)
    return out


def run_one(m: Mutation, model: str) -> dict:
    packet = triage_submission(m.submission, model=model)
    actual_cats = sorted({i.category for i in packet.issues})
    unavailable = packet.meta.llm_failures > 0
    passed = (not unavailable) and packet.decision == m.expected_decision and actual_cats == m.expected_categories
    return {
        "family": m.family,
        "name": m.name,
        "base_case": m.base_case,
        "needs_llm": m.needs_llm,
        "expected_decision": m.expected_decision,
        "expected_categories": m.expected_categories,
        "actual_decision": packet.decision,
        "actual_categories": actual_cats,
        "status": "unavailable" if unavailable else ("pass" if passed else "fail"),
        "rationale": m.rationale,
        "actual_rationale": packet.decision_rationale,
        "llm_calls": packet.meta.llm_calls,
        "llm_failures": packet.meta.llm_failures,
        "unverified_quotes": packet.meta.unverified_quotes,
    }


def render(rows: list[dict], seed: int, model: str, bugs: list[str]) -> str:
    fam = Counter(r["family"] for r in rows)
    ok = Counter(r["family"] for r in rows if r["status"] == "pass")
    bad = Counter(r["family"] for r in rows if r["status"] == "fail")
    na = Counter(r["family"] for r in rows if r["status"] == "unavailable")
    ran = [r for r in rows if r["status"] != "unavailable"]
    L = [
        "# Perturbation suite",
        "",
        f"Generated by `eval/perturb.py --seed {seed}` (model `{model}`). Each mutation's expected decision and issue",
        "categories follow from the policy by construction; see the docstring of `eval/perturb.py` for the families.",
        "Structured mutations replay the committed cache and need no API key; `[LLM]` families change document text and",
        "replay from the cache once their responses have been recorded.",
        "",
        f"**Overall: {sum(ok.values())}/{len(ran)} passed** ({100 * sum(ok.values()) / max(1, len(ran)):.1f}%), "
        f"{sum(bad.values())} failed, {sum(na.values())} unavailable (not cached and no key).",
        "",
        "| family | what is mutated | mutations | pass | fail | pass rate |",
        "|---|---|---|---|---|---|",
    ]
    for f in FAMILIES:
        n = fam[f] - na[f]
        rate = f"{100 * ok[f] / n:.0f}%" if n else "n/a"
        L.append(
            f"| {f} | {FAMILIES[f]} | {fam[f]}{' (' + str(na[f]) + ' unavailable)' if na[f] else ''} | {ok[f]} | {bad[f]} | {rate} |"
        )
    false_ready = [r for r in ran if r["actual_decision"] == READY and r["expected_decision"] != READY]
    L += ["", f"**False READYs: {len(false_ready)}**", ""]
    fails = [r for r in ran if r["status"] == "fail"]
    L += [f"## Failures ({len(fails)})", ""]
    for r in fails:
        L += [
            f"- `{r['family']}/{r['name']}` on {r['base_case']}: expected {r['expected_decision']} {r['expected_categories']}, "
            f"got {r['actual_decision']} {r['actual_categories']}. {r['rationale']}. Pipeline: {r['actual_rationale']}"
        ]
    if not fails:
        L.append("(none)")
    L += ["", "## Bugs found and fixed while building the suite", ""]
    L += [f"- {b}" for b in bugs] or ["(none)"]
    return "\n".join(L) + "\n"


BUGS_FIXED = [
    "`core.TemperatureVital` had no `value_c` field, so a structured Celsius temperature was silently dropped by "
    "`PatientSubmission.model_validate` before the pipeline (which already handled `value_c`) ever saw it. "
    "Added the field; `temp_threshold_c` covers it.",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(ROOT / "data" / "patients_sample_50.jsonl"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-per-family", type=int, default=6)
    ap.add_argument("--family", action="append", help="run only these families (repeatable)")
    ap.add_argument("--skip-llm", action="store_true", help="skip mutations that change document text")
    ap.add_argument("--out-md", default=str(ROOT / "results" / "perturbation.md"))
    ap.add_argument("--out-json", default=str(ROOT / "results" / "perturbation.json"))
    ap.add_argument("--list", action="store_true", help="list families and counts, run nothing")
    args = ap.parse_args()

    bases = load_bases(Path(args.input), args.model)
    muts = generate(bases, args.seed, args.max_per_family)
    if args.family:
        muts = [m for m in muts if m.family in set(args.family)]
    if args.skip_llm:
        muts = [m for m in muts if not m.needs_llm]
    if args.list:
        c = Counter(m.family for m in muts)
        for f in FAMILIES:
            print(f"{f:26s} {c[f]:3d}  {FAMILIES[f]}")
        print(f"total {len(muts)}")
        return
    rows = []
    for i, m in enumerate(muts, 1):
        row = run_one(m, args.model)
        rows.append(row)
        mark = {"pass": ".", "fail": "F", "unavailable": "?"}[row["status"]]
        print(
            f"[{i}/{len(muts)}] {mark} {m.family}/{m.name} ({m.base_case}) -> {row['actual_decision']} {row['actual_categories']}"
        )
    md = render(rows, args.seed, args.model, BUGS_FIXED)
    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text(md)
    Path(args.out_json).write_text(
        json.dumps(
            {
                "seed": args.seed,
                "model": args.model,
                "rows": rows,
                "mutations": [{k: v for k, v in asdict(m).items() if k != "submission"} for m in muts],
            },
            indent=1,
        )
    )
    print(md.split("\n## Failures")[0])
    print(f"wrote {args.out_md} and {args.out_json}")


if __name__ == "__main__":
    if os.environ.get("TRIAGE_ABLATE"):
        print(
            f"note: TRIAGE_ABLATE={os.environ['TRIAGE_ABLATE']} is set; results reflect that ablation", file=sys.stderr
        )
    main()
