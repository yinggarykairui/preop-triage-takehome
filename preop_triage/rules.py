"""Deterministic rule engine. Pure functions over normalized CaseFacts; no I/O, no LLM.

Each rule returns a Check with status PASS / FAIL / UNKNOWN / NOT_APPLICABLE, the inputs it
used and the evidence behind it. `decide()` applies the precedence:
    any ACUTE_SAFETY FAIL -> NOT_CLEARED
    else any FAIL or UNKNOWN -> NEEDS_FOLLOW_UP
    else READY
A false READY is the worst outcome, so UNKNOWN is never silently treated as PASS (A17).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time as dtime

from .normalize import Reading, days_between, most_recent_reading, within_window
from .schemas import Check, Evidence, Issue, ProcedureDateSource

HP_WINDOW_DAYS = 30
CBC_WINDOW = {"LOW": 30, "MODERATE": 30, "HIGH": 14}
CMP_WINDOW = {"HIGH": 14}
VALID_RISKS = ("LOW", "MODERATE", "HIGH")
SBP_LIMIT, DBP_LIMIT, TEMP_LIMIT_F = 180.0, 110.0, 100.4


# ---------------------------------------------------------------------------
# Normalized inputs
# ---------------------------------------------------------------------------


@dataclass
class HPCandidate:
    day: date
    evidence: Evidence
    is_preop: bool
    verified: bool


@dataclass
class ConsentCandidate:
    status: str  # SIGNED | PENDING_OR_UNSIGNED
    matches_procedure: bool | None
    procedure_named: str | None
    evidence: Evidence
    verified: bool


@dataclass
class LabItem:
    canonical: str | None
    day: date | None
    status: str | None
    counts: bool
    evidence: Evidence


@dataclass
class DrugStatus:
    generic: str
    status: str  # CURRENT | NOT_CURRENT | UNKNOWN
    evidence: list[Evidence]
    note: str = ""


@dataclass
class PlanPartFact:
    present: bool
    explicit: bool
    evidence: Evidence | None
    verified: bool


@dataclass
class PlanCandidate:
    generic: str | None
    drug_as_written: str | None
    day: date | None
    doc_evidence: Evidence
    pre_op: PlanPartFact
    post_op: PlanPartFact
    deferred: bool
    deferral_evidence: Evidence | None


@dataclass
class CaseFacts:
    procedure_date: date | None
    procedure_date_source: ProcedureDateSource | None
    procedure_date_evidence: list[Evidence]
    procedure_risk: str | None
    risk_evidence: list[Evidence]
    review_time: str | None
    hps: list[HPCandidate] = field(default_factory=list)
    hp_missing_refs: list[Evidence] = field(default_factory=list)
    consents: list[ConsentCandidate] = field(default_factory=list)
    consent_missing_refs: list[Evidence] = field(default_factory=list)
    labs: list[LabItem] = field(default_factory=list)
    readings: list[Reading] = field(default_factory=list)
    vitals_deferred_refs: list[Evidence] = field(default_factory=list)
    drugs: list[DrugStatus] = field(default_factory=list)
    plans: list[PlanCandidate] = field(default_factory=list)
    failed_documents: list[Evidence] = field(default_factory=list)


def _ref(facts: CaseFacts) -> dict[str, str | None]:
    return {
        "procedure_date": facts.procedure_date.isoformat() if facts.procedure_date else None,
        "review_time": facts.review_time,
    }


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


# ---------------------------------------------------------------------------
# Rule 1: documentation
# ---------------------------------------------------------------------------


def check_hp(facts: CaseFacts) -> Check:
    base = dict(rule="RULE_1", name="H&P within 30 days", category="REQUIRED_DOCUMENTATION",
                reference_dates=_ref(facts), assumptions=["A1", "A2", "A3", "A12"])
    verified = [h for h in facts.hps if h.verified]
    unverified = [h for h in facts.hps if not h.verified]
    if not verified:
        if unverified:
            return Check(**base, status="UNKNOWN", unknown_key="hp_unverified",
                         summary="A document may be an H&P but its supporting quote could not be verified against the text.",
                         evidence=[h.evidence for h in unverified] + facts.hp_missing_refs,
                         resolution="Confirm manually whether a completed H&P exists.")
        return Check(**base, status="FAIL", summary="No completed History and Physical found in the package.",
                     evidence=facts.hp_missing_refs or [Evidence(source="documents", value="no document whose text is an H&P")],
                     resolution="Obtain an H&P completed within 30 days of the procedure date.")
    latest = max(verified, key=lambda h: h.day)
    inputs = {"hp_date": _iso(latest.day), "is_preop_evaluation": latest.is_preop,
              "all_hp_dates": sorted(_iso(h.day) for h in verified)}
    if facts.procedure_date is None:
        return Check(**base, status="UNKNOWN", unknown_key="procedure_date", inputs=inputs,
                     summary=f"H&P dated {latest.day} found, but the window cannot be evaluated without a procedure date.",
                     evidence=[latest.evidence], resolution="Confirm the procedure date.")
    delta = days_between(facts.procedure_date, latest.day)
    inputs["days_before_procedure"] = delta
    ok = within_window(facts.procedure_date, latest.day, HP_WINDOW_DAYS)
    if ok:
        return Check(**base, status="PASS", inputs=inputs, evidence=[latest.evidence],
                     summary=f"Most recent H&P {latest.day} is {delta} days before the procedure (limit {HP_WINDOW_DAYS}).")
    why = "after the procedure date" if delta < 0 else f"{delta} days before the procedure (limit {HP_WINDOW_DAYS})"
    return Check(**base, status="FAIL", inputs=inputs, evidence=[latest.evidence],
                 summary=f"Most recent H&P {latest.day} is {why}; outdated.",
                 resolution="Obtain an updated H&P within 30 days of the procedure date.")


def check_consent(facts: CaseFacts) -> Check:
    base = dict(rule="RULE_1", name="Signed surgical consent", category="REQUIRED_DOCUMENTATION",
                reference_dates=_ref(facts), assumptions=["A13"])
    signed_ok = [c for c in facts.consents if c.status == "SIGNED" and c.matches_procedure is not False]
    signed_ok_verified = [c for c in signed_ok if c.verified]
    if signed_ok_verified:
        best = signed_ok_verified[-1]
        return Check(**base, status="PASS", evidence=[best.evidence],
                     inputs={"procedure_on_consent": best.procedure_named, "signed_date": best.evidence.date},
                     summary=f"Consent for '{best.procedure_named}' signed by the patient ({best.evidence.date}).")
    if signed_ok:  # signed but quote unverifiable
        return Check(**base, status="UNKNOWN", unknown_key="consent_unverified", evidence=[c.evidence for c in signed_ok],
                     summary="A consent appears signed but the supporting quote could not be verified.",
                     resolution="Confirm the signed consent manually.")
    wrong_proc = [c for c in facts.consents if c.status == "SIGNED" and c.matches_procedure is False]
    pending = [c for c in facts.consents if c.status != "SIGNED"]
    ev = [c.evidence for c in wrong_proc + pending] + facts.consent_missing_refs
    if wrong_proc and not pending:
        summary = "Only signed consent on file is for a different procedure (" + ", ".join(
            f"'{c.procedure_named}'" for c in wrong_proc) + ")."
    elif pending:
        summary = "Consent is not signed by the patient (pending/unsigned)."
        if wrong_proc:
            summary += " A signed consent exists but for a different procedure."
    else:
        summary = "No surgical consent found in the package."
        ev = ev or [Evidence(source="documents", value="no document whose text is a consent")]
    return Check(**base, status="FAIL", summary=summary, evidence=ev,
                 inputs={"consents_found": len(facts.consents)},
                 resolution="Obtain a patient-signed consent for the planned procedure.")


# ---------------------------------------------------------------------------
# Rule 2: testing
# ---------------------------------------------------------------------------


def check_risk(facts: CaseFacts) -> Check:
    base = dict(rule="RULE_2", name="Procedure risk category", category="MISSING_REQUIRED_DATA",
                reference_dates=_ref(facts), assumptions=["A5"])
    if facts.procedure_risk in VALID_RISKS:
        return Check(**base, status="PASS", inputs={"procedure_risk": facts.procedure_risk}, evidence=facts.risk_evidence,
                     summary=f"Procedure risk is {facts.procedure_risk}.")
    return Check(**base, status="UNKNOWN", unknown_key="procedure_risk", evidence=facts.risk_evidence,
                 inputs={"procedure_risk": facts.procedure_risk},
                 summary="Procedure risk is missing or not one of LOW/MODERATE/HIGH; the testing requirements cannot be determined.",
                 resolution="Have the surgical team assign the procedure risk category.")


def check_procedure_date(facts: CaseFacts) -> Check:
    base = dict(rule="REFERENCE", name="Procedure date", category="MISSING_REQUIRED_DATA",
                reference_dates=_ref(facts), assumptions=["A4"])
    if facts.procedure_date:
        src = facts.procedure_date_source
        return Check(**base, status="PASS", evidence=facts.procedure_date_evidence,
                     inputs={"procedure_date": _iso(facts.procedure_date), "source": src.source if src else None},
                     summary=f"Procedure date {facts.procedure_date} ({src.source if src else 'unknown source'}).")
    return Check(**base, status="UNKNOWN", unknown_key="procedure_date", evidence=facts.procedure_date_evidence,
                 summary="No procedure date in the structured field or the documents; H&P and lab windows cannot be evaluated.",
                 resolution="Confirm the scheduled procedure date.")


def _latest_lab(facts: CaseFacts, canonical: str) -> tuple[LabItem | None, list[LabItem]]:
    """Most recent qualifying result on/before the procedure date (A3, A11). Also returns skipped items."""
    items = [l for l in facts.labs if l.canonical == canonical]
    skipped = [l for l in items if not l.counts or l.day is None
               or (facts.procedure_date is not None and l.day > facts.procedure_date)]
    usable = [l for l in items if l not in skipped]
    if not usable:
        return None, skipped
    return max(usable, key=lambda l: l.day), skipped  # type: ignore[arg-type]


def check_lab(facts: CaseFacts, canonical: str) -> Check:
    windows = CBC_WINDOW if canonical == "CBC" else CMP_WINDOW
    base = dict(rule="RULE_2", name=f"{canonical} within window", category="REQUIRED_TESTING",
                reference_dates=_ref(facts), assumptions=["A1", "A2", "A3", "A5", "A11"])
    risk = facts.procedure_risk if facts.procedure_risk in VALID_RISKS else None
    possible_risks = [risk] if risk else list(VALID_RISKS)
    required_under = [r for r in possible_risks if r in windows]
    if not required_under:
        return Check(**base, status="NOT_APPLICABLE", inputs={"procedure_risk": risk},
                     summary=f"{canonical} is not required for {risk} risk procedures.")
    latest, skipped = _latest_lab(facts, canonical)
    skipped_ev = [l.evidence for l in skipped]
    inputs: dict[str, object] = {"procedure_risk": risk, "skipped_results": len(skipped)}
    if latest is None:
        if risk is None and len(required_under) < len(VALID_RISKS):
            # e.g. CMP: only required if HIGH; without a risk we cannot say it is missing.
            return Check(**base, status="UNKNOWN", unknown_key="procedure_risk", inputs=inputs, evidence=skipped_ev,
                         summary=f"No {canonical} on file; whether one is required depends on the (missing) risk category.")
        return Check(**base, status="FAIL", inputs=inputs, evidence=skipped_ev or [Evidence(source="labs", value=f"no final {canonical} result")],
                     summary=f"No qualifying {canonical} result on file" + (" (only entered-in-error/non-final results)." if skipped else "."),
                     resolution=f"Obtain a {canonical}" + (f" within {windows[risk]} days of the procedure." if risk else "."))
    inputs["result_date"] = _iso(latest.day)
    if facts.procedure_date is None:
        return Check(**base, status="UNKNOWN", unknown_key="procedure_date", inputs=inputs, evidence=[latest.evidence],
                     summary=f"Most recent {canonical} is {latest.day}; window cannot be evaluated without a procedure date.")
    delta = days_between(facts.procedure_date, latest.day)
    inputs["days_before_procedure"] = delta
    outcomes = {r: within_window(facts.procedure_date, latest.day, windows[r]) for r in required_under}
    inputs["window_days"] = {r: windows[r] for r in required_under}
    if all(outcomes.values()):
        lim = windows[risk] if risk else min(windows[r] for r in required_under)
        return Check(**base, status="PASS", inputs=inputs, evidence=[latest.evidence] + skipped_ev,
                     summary=f"Most recent {canonical} {latest.day} is {delta} days before the procedure (limit {lim}).")
    if not any(outcomes.values()):
        lim = windows[risk] if risk else max(windows[r] for r in required_under)
        return Check(**base, status="FAIL", inputs=inputs, evidence=[latest.evidence] + skipped_ev,
                     summary=f"Most recent {canonical} {latest.day} is {delta} days before the procedure; outside the {lim}-day window.",
                     resolution=f"Repeat the {canonical} within {lim} days of the procedure.")
    return Check(**base, status="UNKNOWN", unknown_key="procedure_risk", inputs=inputs, evidence=[latest.evidence],
                 summary=f"Most recent {canonical} is {delta} days out, which passes for some risk levels but not others; risk category is missing.")


# ---------------------------------------------------------------------------
# Rule 3: anticoagulation
# ---------------------------------------------------------------------------


def check_anticoagulation(facts: CaseFacts) -> list[Check]:
    base = dict(rule="RULE_3", name="Perioperative anticoagulation plan", category="ANTICOAGULATION_MANAGEMENT",
                reference_dates=_ref(facts), assumptions=["A14", "A15", "A16"])
    checks: list[Check] = []
    current = [d for d in facts.drugs if d.status == "CURRENT"]
    unknown = [d for d in facts.drugs if d.status == "UNKNOWN"]
    for d in unknown:
        checks.append(Check(**{**base, "name": f"Anticoagulant status: {d.generic}"}, status="UNKNOWN",
                            unknown_key=f"anticoagulant_status:{d.generic}", evidence=d.evidence,
                            inputs={"drug": d.generic, "note": d.note},
                            summary=f"Cannot tell whether the patient is currently taking {d.generic}; {d.note or 'status unresolved'}.",
                            resolution=f"Confirm whether the patient is currently taking {d.generic}; if so, obtain a perioperative plan."))
    for d in current:
        plans = [p for p in facts.plans if p.generic == d.generic]
        other = [p for p in facts.plans if p.generic and p.generic != d.generic]
        name = f"Plan for {d.generic}"
        if not plans:
            ev = list(d.evidence) + [p.doc_evidence for p in other] + [e for p in other for e in (p.pre_op.evidence, p.post_op.evidence) if e]
            if other:
                names = ", ".join(sorted({p.drug_as_written or p.generic or "?" for p in other}))
                summary = f"Patient is on {d.generic}, but the only perioperative plan names {names}; the plan does not cover the active drug (ambiguous)."
            else:
                summary = f"Patient is on {d.generic} and no perioperative anticoagulation plan is documented."
            checks.append(Check(**{**base, "name": name}, status="FAIL", evidence=ev, inputs={"drug": d.generic, "plans_for_other_drugs": len(other)},
                                summary=summary, resolution=f"Obtain a documented plan naming {d.generic} with pre-op hold and post-op resumption instructions."))
            continue
        plan = max(plans, key=lambda p: (p.day or date.min))
        pre, post = plan.pre_op, plan.post_op
        pre_ok = pre.present and pre.explicit and pre.verified
        post_ok = post.present and post.explicit and post.verified
        ev = list(d.evidence) + [plan.doc_evidence] + [e for e in (pre.evidence, post.evidence, plan.deferral_evidence) if e]
        inputs = {"drug": d.generic, "plan_date": _iso(plan.day), "plan_drug_as_written": plan.drug_as_written,
                  "pre_op": {"present": pre.present, "explicit": pre.explicit, "verified": pre.verified},
                  "post_op": {"present": post.present, "explicit": post.explicit, "verified": post.verified},
                  "deferred": plan.deferred}
        if pre_ok and post_ok and not plan.deferred:
            checks.append(Check(**{**base, "name": name}, status="PASS", evidence=ev, inputs=inputs,
                                summary=f"Plan dated {plan.day} names {plan.drug_as_written} with explicit pre-op and post-op instructions."))
            continue
        gaps = []
        if not pre.present:
            gaps.append("no pre-op hold instruction")
        elif not pre.explicit:
            gaps.append("pre-op instruction is not explicit")
        elif not pre.verified:
            gaps.append("pre-op instruction quote could not be verified")
        if not post.present:
            gaps.append("no post-op resumption instruction")
        elif not post.explicit:
            gaps.append("post-op instruction is not explicit")
        elif not post.verified:
            gaps.append("post-op instruction quote could not be verified")
        if plan.deferred:
            gaps.append("management deferred to another team")
        older_complete = [p for p in plans if p is not plan and p.pre_op.present and p.pre_op.explicit and p.pre_op.verified
                          and p.post_op.present and p.post_op.explicit and p.post_op.verified and not p.deferred]
        if older_complete:
            gaps.append(f"an earlier plan ({max(older_complete, key=lambda p: p.day or date.min).day}) was complete; the later note supersedes it")
            ev += [e for p in older_complete for e in (p.doc_evidence, p.pre_op.evidence, p.post_op.evidence) if e]
        unverified_only = all("verified" in g for g in gaps)
        status = "UNKNOWN" if unverified_only else "FAIL"
        checks.append(Check(**{**base, "name": name}, status=status, evidence=ev, inputs=inputs,
                            unknown_key=f"plan_unverified:{d.generic}" if unverified_only else None,
                            summary=f"Plan dated {plan.day} for {d.generic} is incomplete: " + "; ".join(gaps) + ".",
                            resolution=f"Obtain explicit pre-op hold and post-op resumption instructions for {d.generic}."))
    if not checks:
        ev = [e for d in facts.drugs for e in d.evidence]
        checks.append(Check(**base, status="NOT_APPLICABLE", evidence=ev,
                            inputs={"not_current": [d.generic for d in facts.drugs if d.status == "NOT_CURRENT"]},
                            summary="Patient is not currently on an anticoagulant; no plan required."))
    return checks


# ---------------------------------------------------------------------------
# Rule 4: acute safety
# ---------------------------------------------------------------------------


def _reading_evidence(r: Reading) -> Evidence:
    value = f"BP {r.systolic:g}/{r.diastolic:g}" if r.kind == "BP" else f"Temp {r.temp_f} F"
    when = r.day.isoformat() + (f" {r.clock.strftime('%H:%M')}" if r.clock else "")
    return Evidence(source=r.source, value=f"{value} @ {when}", doc_id=r.doc_id, doc_type=r.doc_type,
                    date=r.day.isoformat(), quote=r.quote, verified=r.verified)


def check_vital(facts: CaseFacts, kind: str) -> Check:
    label = "Blood pressure" if kind == "BP" else "Temperature"
    base = dict(rule="RULE_4", name=f"{label} exclusion", category="ACUTE_SAFETY_EXCLUSION",
                reference_dates=_ref(facts), assumptions=["A6", "A7", "A8", "A9", "A10"])
    readings = [r for r in facts.readings if r.kind == kind]
    verified = [r for r in readings if r.verified]
    if not verified:
        key = "blood_pressure" if kind == "BP" else "temperature"
        ev = [_reading_evidence(r) for r in readings] + facts.vitals_deferred_refs
        msg = (f"A {label.lower()} reading was extracted but could not be verified against its document."
               if readings else f"No {label.lower()} reading anywhere in the structured vitals or the documents.")
        return Check(**base, status="UNKNOWN", unknown_key=key, evidence=ev, inputs={"readings": 0},
                     summary=msg, resolution=f"Record a current {label.lower()} before the procedure.")
    latest = most_recent_reading(verified)
    assert latest is not None
    tied = [r for r in verified if r.day == latest.day]
    inputs: dict[str, object] = {"readings_considered": len(verified), "latest_date": _iso(latest.day),
                                 "latest_time": latest.clock.strftime("%H:%M") if latest.clock else None,
                                 "same_day_readings": len(tied), "tie_break_applied": len(tied) > 1 and any(r.clock is None for r in tied)}
    others = sorted((r for r in verified if r is not latest), key=lambda r: (r.day, r.clock or dtime(0, 0)), reverse=True)[:3]
    ev = [_reading_evidence(latest)] + [_reading_evidence(r) for r in others]
    if kind == "BP":
        s, d = latest.systolic or 0.0, latest.diastolic or 0.0
        inputs.update({"systolic": s, "diastolic": d, "limits": {"systolic_ge": SBP_LIMIT, "diastolic_ge": DBP_LIMIT}})
        if s >= SBP_LIMIT or d >= DBP_LIMIT:
            which = " and ".join(w for w, hit in (("SBP >= 180", s >= SBP_LIMIT), ("DBP >= 110", d >= DBP_LIMIT)) if hit)
            return Check(**base, status="FAIL", inputs=inputs, evidence=ev,
                         summary=f"Most recent BP {s:g}/{d:g} on {latest.day} meets the exclusion ({which}).",
                         resolution="Recheck blood pressure; an in-range recheck clears the exclusion.")
        return Check(**base, status="PASS", inputs=inputs, evidence=ev,
                     summary=f"Most recent BP {s:g}/{d:g} on {latest.day} is below 180/110.")
    t = latest.temp_f or 0.0
    inputs.update({"temp_f": t, "limit_gt": TEMP_LIMIT_F})
    if t > TEMP_LIMIT_F:
        return Check(**base, status="FAIL", inputs=inputs, evidence=ev,
                     summary=f"Most recent temperature {t} F on {latest.day} is above 100.4 F.",
                     resolution="Recheck temperature; an in-range recheck clears the exclusion.")
    return Check(**base, status="PASS", inputs=inputs, evidence=ev,
                 summary=f"Most recent temperature {t} F on {latest.day} is not above 100.4 F.")


# ---------------------------------------------------------------------------
# Extraction integrity
# ---------------------------------------------------------------------------


def check_extraction(facts: CaseFacts) -> Check | None:
    if not facts.failed_documents:
        return None
    return Check(rule="PIPELINE", name="Document extraction", category="MISSING_REQUIRED_DATA", status="UNKNOWN",
                 unknown_key="document_extraction", evidence=facts.failed_documents, assumptions=["A17"],
                 reference_dates=_ref(facts), inputs={"failed_documents": len(facts.failed_documents)},
                 summary=f"{len(facts.failed_documents)} document(s) could not be read by the extractor; their contents are unknown.",
                 resolution="Review the listed documents manually.")


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


def run_all_checks(facts: CaseFacts) -> list[Check]:
    checks = [check_procedure_date(facts), check_risk(facts), check_hp(facts), check_consent(facts),
              check_lab(facts, "CBC"), check_lab(facts, "CMP")]
    checks += check_anticoagulation(facts)
    checks += [check_vital(facts, "BP"), check_vital(facts, "TEMP")]
    ex = check_extraction(facts)
    if ex:
        checks.append(ex)
    return checks


UNKNOWN_LABELS = {
    "procedure_date": "Procedure date",
    "procedure_risk": "Procedure risk category",
    "blood_pressure": "Blood pressure reading",
    "temperature": "Temperature reading",
    "document_extraction": "Document contents",
}


def build_issues(checks: list[Check]) -> list[Issue]:
    issues: list[Issue] = []
    for c in checks:
        if c.status == "FAIL":
            issues.append(Issue(category=c.category, rule=c.rule, summary=c.summary, evidence=c.evidence,
                                resolution=c.resolution or "Resolve and re-submit.", description=c.summary))
    # UNKNOWN -> one MISSING_REQUIRED_DATA issue per missing datum (A19)
    by_key: dict[str, list[Check]] = {}
    for c in checks:
        if c.status == "UNKNOWN":
            by_key.setdefault(c.unknown_key or c.name, []).append(c)
    for key, group in by_key.items():
        label = UNKNOWN_LABELS.get(key) or key.replace("_", " ").replace(":", ": ")
        blocked = sorted({g.name for g in group})
        primary = group[0]
        ev: list[Evidence] = []
        seen: set[str] = set()
        for g in group:
            for e in g.evidence:
                sig = e.model_dump_json()
                if sig not in seen:
                    seen.add(sig)
                    ev.append(e)
        if not ev:
            ev = [Evidence(source="submission", value=f"{label}: not found")]
        summary = f"{label} is missing/unknown; cannot evaluate: {', '.join(blocked)}. {primary.summary}"
        issues.append(Issue(category="MISSING_REQUIRED_DATA", rule=primary.rule, summary=summary, evidence=ev,
                            resolution=primary.resolution or f"Provide the {label.lower()}.", description=summary))
    return issues


def decide(checks: list[Check]) -> tuple[str, str]:
    """Return (decision, one-sentence rationale)."""
    safety = [c for c in checks if c.status == "FAIL" and c.category == "ACUTE_SAFETY_EXCLUSION"]
    fails = [c for c in checks if c.status == "FAIL" and c.category != "ACUTE_SAFETY_EXCLUSION"]
    unknowns = [c for c in checks if c.status == "UNKNOWN"]
    if safety:
        extra = f"; also {len(fails) + len(unknowns)} follow-up item(s)" if (fails or unknowns) else ""
        return "NOT_CLEARED", "Rule 4 acute safety exclusion: " + "; ".join(c.summary for c in safety) + extra + "."
    if fails or unknowns:
        parts = [f"{c.rule} {c.name}" for c in fails] + [f"missing data ({c.unknown_key})" for c in unknowns]
        return "NEEDS_FOLLOW_UP", "Not ready because of: " + "; ".join(dict.fromkeys(parts)) + "."
    return "READY", "All rules pass: documentation current, required testing in window, anticoagulation plan complete or not applicable, no acute safety exclusion."
