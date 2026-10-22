"""Orchestration: raw JSON -> normalize -> extract -> verify -> rules -> evidence packet."""

from __future__ import annotations

import os
from datetime import date

from . import PIPELINE_VERSION
from .assumptions import ASSUMPTIONS
from .extract import DocExtraction, extract_all
from .llm import CachedLLM
from .normalize import (
    Reading, canonical_anticoagulant, canonical_lab, is_antiplatelet, lab_status_counts,
    parse_clock_time, parse_date, parse_datetime, temperature_to_f,
)
from .rules import (
    VALID_RISKS, CaseFacts, ConsentCandidate, DrugStatus, HPCandidate, LabItem, PlanCandidate,
    PlanPartFact, build_issues, decide, run_all_checks,
)
from .schemas import Evidence, Meta, ProcedureDateSource, ReferenceDates, TriagePacket


def _doc_ev(ex: DocExtraction, quote: str | None, value: str | None = None, date_: str | None = None) -> Evidence:
    return Evidence(source="document", doc_id=ex.doc_id, doc_type=ex.doc_type, date=date_ or ex.doc_date,
                    quote=quote, value=value, verified=ex.verified(quote))


# ---------------------------------------------------------------------------
# Building CaseFacts
# ---------------------------------------------------------------------------


def _procedure_date(sub: dict, exs: list[DocExtraction]):
    proc = sub.get("procedure") or {}
    structured = parse_date(proc.get("procedure_date"))
    if structured:
        return structured, ProcedureDateSource(source="procedure.procedure_date"), [
            Evidence(source="procedure.procedure_date", value=str(proc.get("procedure_date")))]
    # A4: fall back to dates stated in documents, only if they all agree
    stated: dict[date, Evidence] = {}
    tbd: list[Evidence] = []
    evidence = [Evidence(source="procedure.procedure_date", value="null")]
    for ex in exs:
        f = ex.facts
        if not f:
            continue
        pd = f.procedure_date
        ev = _doc_ev(ex, pd.quote)
        if pd.status == "DATE_STATED" and ev.verified:
            d = parse_date(pd.date)
            if d:
                stated.setdefault(d, ev)
        elif pd.status == "UNSCHEDULED_OR_TBD":
            tbd.append(ev)
    if len(stated) == 1:
        d, ev = next(iter(stated.items()))
        return d, ProcedureDateSource(source="document", doc_id=ev.doc_id, quote=ev.quote), evidence + [ev]
    return None, None, evidence + list(stated.values()) + tbd


def _risk(sub: dict):
    proc = sub.get("procedure") or {}
    raw = proc.get("procedure_risk")
    risk = str(raw).strip().upper() if raw is not None else None
    ev = [Evidence(source="procedure.procedure_risk", value="null" if raw is None else str(raw))]
    return (risk if risk in VALID_RISKS else None), ev


def _review_time(sub: dict) -> str | None:
    meta = sub.get("metadata") or {}
    rt = meta.get("submission_received_at")
    if rt:
        return str(rt)
    dates = [v.get("date") for v in sub.get("vitals") or [] if v.get("date")]
    return max(dates) if dates else None  # A6 fallback


def _hps(exs: list[DocExtraction]):
    hps, missing = [], []
    for ex in exs:
        f = ex.facts
        if not f:
            continue
        if f.hp.is_completed_hp:
            day = parse_date(f.hp.date_of_service) or parse_date(ex.doc_date)
            if day is None:
                continue
            ev = _doc_ev(ex, f.hp.quote, value=f"H&P dated {day}", date_=day.isoformat())
            hps.append(HPCandidate(day=day, evidence=ev, is_preop=f.hp.is_preop_evaluation_for_planned_procedure, verified=ev.verified))
        if f.hp.references_hp_missing:
            ev = _doc_ev(ex, f.hp.references_hp_missing_quote, value="note says H&P not on file")
            if ev.verified:
                missing.append(ev)
    return hps, missing


def _consents(exs: list[DocExtraction]):
    consents, missing = [], []
    for ex in exs:
        f = ex.facts
        if not f:
            continue
        c = f.consent
        if c.patient_signed != "NOT_A_CONSENT":
            ev = _doc_ev(ex, c.quote, value=f"consent {c.patient_signed.lower()} for '{c.procedure_named}'",
                         date_=c.signed_date or ex.doc_date)
            consents.append(ConsentCandidate(status=c.patient_signed, matches_procedure=c.matches_planned_procedure,
                                             procedure_named=c.procedure_named, evidence=ev, verified=ev.verified))
        if c.references_consent_missing:
            ev = _doc_ev(ex, c.references_consent_missing_quote, value="note says consent not yet obtained")
            if ev.verified:
                missing.append(ev)
    # chronological so the "best" signed consent is the latest one
    consents.sort(key=lambda c: c.evidence.date or "")
    return consents, missing


def _labs(sub: dict) -> list[LabItem]:
    out = []
    for i, lab in enumerate(sub.get("labs") or []):
        canonical = canonical_lab(lab.get("code"), lab.get("display"))
        day = parse_date(lab.get("effective_at"))
        counts = lab_status_counts(lab.get("status"))
        ev = Evidence(source=f"labs[{i}]", date=day.isoformat() if day else None,
                      value=f"{lab.get('code')} '{lab.get('display')}' status={lab.get('status')} effective={lab.get('effective_at')}"
                            + ("" if counts else " (does not count)"))
        out.append(LabItem(canonical=canonical, day=day, status=lab.get("status"), counts=counts, evidence=ev))
    return out


def _readings(sub: dict, exs: list[DocExtraction]):
    readings: list[Reading] = []
    deferred: list[Evidence] = []
    for i, v in enumerate(sub.get("vitals") or []):
        dt = parse_datetime(v.get("date"))
        if dt is None:
            continue
        t = str(v.get("type") or "").lower()
        if t == "blood_pressure" and v.get("systolic") is not None and v.get("diastolic") is not None:
            readings.append(Reading(kind="BP", day=dt.date(), clock=dt.time(), systolic=float(v["systolic"]),
                                    diastolic=float(v["diastolic"]), source=f"vitals[{i}]",
                                    quote=f"{v.get('systolic')}/{v.get('diastolic')} ({v.get('source')})"))
        elif t == "temperature":
            if v.get("value_f") is not None:
                temp_f = float(v["value_f"])
            elif v.get("value_c") is not None:
                temp_f = temperature_to_f(float(v["value_c"]), "C")
            else:
                continue
            readings.append(Reading(kind="TEMP", day=dt.date(), clock=dt.time(), temp_f=temp_f, source=f"vitals[{i}]",
                                    quote=f"{temp_f} F ({v.get('source')})"))
    for ex in exs:
        f = ex.facts
        if not f:
            continue
        for r in f.vitals:
            if not r.measured_at_this_encounter:
                continue
            day = parse_date(r.date) or parse_date(ex.doc_date)
            if day is None:
                continue
            verified = ex.verified(r.quote)
            common = dict(day=day, clock=parse_clock_time(r.time), source="document", doc_id=ex.doc_id,
                          doc_type=ex.doc_type, quote=r.quote, verified=verified)
            if r.kind == "BP" and r.systolic is not None and r.diastolic is not None:
                readings.append(Reading(kind="BP", systolic=float(r.systolic), diastolic=float(r.diastolic), **common))
            elif r.kind == "TEMP" and r.temperature_value is not None:
                readings.append(Reading(kind="TEMP", temp_f=temperature_to_f(r.temperature_value, r.temperature_unit), **common))
        if f.vitals_deferred_or_not_recorded:
            ev = _doc_ev(ex, f.vitals_deferred_quote, value="vitals not recorded in note")
            if ev.verified:
                deferred.append(ev)
    return readings, deferred


def _drugs(sub: dict, exs: list[DocExtraction]) -> list[DrugStatus]:
    """A15: merge the med list with note mentions, per generic drug."""
    list_status: dict[str, tuple[str, Evidence]] = {}
    for i, m in enumerate(sub.get("medications") or []):
        g = canonical_anticoagulant(m.get("name"))
        if not g or is_antiplatelet(m.get("name")) and g is None:
            continue
        active = m.get("active")
        st = "CURRENT" if active is True else "NOT_CURRENT" if active is False else "UNKNOWN"
        ev = Evidence(source=f"medications[{i}]", value=f"{m.get('name')} (active={active})")
        prev = list_status.get(g)
        if prev is None or (prev[0] != "CURRENT" and st == "CURRENT"):
            list_status[g] = (st, ev)
    # most recent note mention per drug (by document date), unverified mentions become UNKNOWN
    mentions: dict[str, list[tuple[str, str, Evidence]]] = {}
    for ex in exs:
        if not ex.anticoag:
            continue
        for m in ex.anticoag.mentions:
            g = canonical_anticoagulant(m.drug_as_written)
            if not g or m.status == "OTHER":
                continue
            ev = _doc_ev(ex, m.quote, value=f"{m.drug_as_written}: {m.status.lower().replace('_', ' ')}")
            st = {"CURRENTLY_TAKING": "CURRENT", "NOT_CURRENTLY_TAKING": "NOT_CURRENT"}.get(m.status, "UNKNOWN")
            if not ev.verified:
                st = "UNKNOWN"
            mentions.setdefault(g, []).append((ex.doc_date or "", st, ev))
    out: list[DrugStatus] = []
    for g in sorted(set(list_status) | set(mentions)):
        ms = sorted(mentions.get(g, []), key=lambda t: t[0])
        latest_note = ms[-1][1] if ms else None
        ev = ([list_status[g][1]] if g in list_status else []) + [t[2] for t in ms]
        ls = list_status[g][0] if g in list_status else None
        if ls == "CURRENT":
            status, note = "CURRENT", "active on the medication list"
        elif ls == "NOT_CURRENT":
            if latest_note == "CURRENT":
                status, note = "UNKNOWN", "med list says inactive but the most recent note says currently taking"
            else:
                status, note = "NOT_CURRENT", "inactive on the medication list" + ("; notes agree" if ms else "")
        elif ls == "UNKNOWN":
            if latest_note in ("CURRENT", "NOT_CURRENT"):
                status, note = latest_note, "active flag is null; most recent note resolves it"
            else:
                status, note = "UNKNOWN", "active flag is null and the notes do not resolve whether the patient is taking it"
        else:  # not on the med list at all
            if latest_note == "CURRENT":
                status, note = "CURRENT", "not on the reconciled med list; a note says the patient currently takes it"
            elif latest_note == "NOT_CURRENT":
                status, note = "NOT_CURRENT", "mentioned in notes as not currently taken"
            else:
                status, note = "UNKNOWN", "a note is unsure whether the patient takes it"
        out.append(DrugStatus(generic=g, status=status, evidence=ev, note=note))
    return out


def _plans(exs: list[DocExtraction]) -> list[PlanCandidate]:
    out = []
    for ex in exs:
        ac = ex.anticoag
        if not ac or not ac.plan.is_perioperative_plan:
            continue
        p = ac.plan

        def part(pp) -> PlanPartFact:
            ev = _doc_ev(ex, pp.quote) if pp.quote else None
            return PlanPartFact(present=pp.present, explicit=pp.explicit, evidence=ev, verified=(ev.verified if ev else not pp.present))

        out.append(PlanCandidate(
            generic=canonical_anticoagulant(p.drug_named), drug_as_written=p.drug_named, day=parse_date(ex.doc_date),
            doc_evidence=_doc_ev(ex, None, value=f"perioperative plan for {p.drug_named}"),
            pre_op=part(p.pre_op), post_op=part(p.post_op), deferred=p.deferred_to_another_team,
            deferral_evidence=_doc_ev(ex, p.deferral_quote) if p.deferral_quote else None))
    return out


def build_case_facts(sub: dict, exs: list[DocExtraction]) -> CaseFacts:
    pd, pd_src, pd_ev = _procedure_date(sub, exs)
    risk, risk_ev = _risk(sub)
    hps, hp_missing = _hps(exs)
    consents, consent_missing = _consents(exs)
    readings, deferred = _readings(sub, exs)
    failed = [Evidence(source="document", doc_id=ex.doc_id, doc_type=ex.doc_type, date=ex.doc_date,
                       value="extraction failed: " + "; ".join(ex.errors)) for ex in exs if ex.errors]
    return CaseFacts(
        procedure_date=pd, procedure_date_source=pd_src, procedure_date_evidence=pd_ev,
        procedure_risk=risk, risk_evidence=risk_ev, review_time=_review_time(sub),
        hps=hps, hp_missing_refs=hp_missing, consents=consents, consent_missing_refs=consent_missing,
        labs=_labs(sub), readings=readings, vitals_deferred_refs=deferred,
        drugs=_drugs(sub, exs), plans=_plans(exs), failed_documents=failed,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def triage(sub: dict, *, model: str, llm: CachedLLM | None = None) -> TriagePacket:
    llm = llm or CachedLLM(model=model)
    proc = sub.get("procedure") or {}
    exs = extract_all(llm, sub.get("documents") or [], proc.get("procedure_type"),
                      max_workers=int(os.environ.get("LLM_MAX_WORKERS", "6")))
    facts = build_case_facts(sub, exs)
    return assemble_packet(sub, facts, exs, llm)


def assemble_packet(sub: dict, facts: CaseFacts, exs: list[DocExtraction], llm: CachedLLM) -> TriagePacket:
    checks = run_all_checks(facts)
    decision, rationale = decide(checks)
    issues = build_issues(checks)
    applied = sorted({a for c in checks for a in c.assumptions} | {"A17", "A18", "A19"}, key=lambda a: int(a[1:]))
    proc = sub.get("procedure") or {}
    patient = sub.get("patient") or {}
    return TriagePacket(
        case_id=proc.get("case_id"), patient_id=patient.get("id"),
        decision=decision, decision_rationale=rationale, explanation=rationale,
        reference_dates=ReferenceDates(
            procedure_date=facts.procedure_date.isoformat() if facts.procedure_date else None,
            procedure_date_source=facts.procedure_date_source, review_time=facts.review_time,
            procedure_risk=facts.procedure_risk),
        issues=issues, checks=checks, assumptions_applied=applied,
        meta=Meta(model=llm.model, provider=llm.provider_name, pipeline_version=PIPELINE_VERSION,
                  llm_calls=llm.stats.calls, llm_cache_hits=llm.stats.cache_hits, llm_failures=llm.stats.failures,
                  unverified_quotes=sum(len(ex.unverified) for ex in exs),
                  unverified_quote_details=[f"{ex.doc_id}: {u}" for ex in exs for u in ex.unverified],
                  documents_extracted=sum(1 for ex in exs if ex.facts is not None),
                  documents_failed=[ex.doc_id for ex in exs if ex.errors]),
    )


def assumption_text(ids: list[str]) -> dict[str, str]:
    return {i: ASSUMPTIONS[i] for i in ids if i in ASSUMPTIONS}
