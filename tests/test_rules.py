"""Rule-engine tests: pure code, no LLM, no network."""
from __future__ import annotations

from datetime import date, time

import pytest

from preop_triage.normalize import Reading, most_recent_reading
from preop_triage.rules import (
    CaseFacts, ConsentCandidate, DrugStatus, HPCandidate, LabItem, PlanCandidate, PlanPartFact,
    build_issues, check_anticoagulation, check_consent, check_hp, check_lab, check_vital, decide, run_all_checks,
)
from preop_triage.schemas import Evidence, ProcedureDateSource

PD = date(2026, 3, 31)


def ev(**kw) -> Evidence:
    return Evidence(**{"source": "document", "doc_id": "d1", "quote": "x", **kw})


def facts(**kw) -> CaseFacts:
    base = dict(procedure_date=PD, procedure_date_source=ProcedureDateSource(source="procedure.procedure_date"),
                procedure_date_evidence=[Evidence(source="procedure.procedure_date", value=PD.isoformat())],
                procedure_risk="LOW", risk_evidence=[Evidence(source="procedure.procedure_risk", value="LOW")], review_time="2026-03-31T00:00:00Z")
    base.update(kw)
    return CaseFacts(**base)


def hp(d: date, verified=True) -> HPCandidate:
    return HPCandidate(day=d, evidence=ev(date=d.isoformat()), is_preop=True, verified=verified)


def lab(canonical: str, d: date, status="final") -> LabItem:
    return LabItem(canonical=canonical, day=d, status=status, counts=status in {"final", "corrected", "amended"},
                   evidence=Evidence(source="labs[0]", value=canonical))


def bp(s: float, d: float, day=PD, clock=time(9, 0), verified=True, source="vitals[0]") -> Reading:
    return Reading(kind="BP", day=day, clock=clock, systolic=s, diastolic=d, source=source, verified=verified)


def temp(f: float, day=PD, clock=time(9, 0), verified=True) -> Reading:
    return Reading(kind="TEMP", day=day, clock=clock, temp_f=f, source="vitals[0]", verified=verified)


# --- Rule 1: H&P window ------------------------------------------------------

@pytest.mark.parametrize("days,status", [(0, "PASS"), (29, "PASS"), (30, "PASS"), (31, "FAIL"), (-1, "FAIL")])
def test_hp_window_boundaries(days, status):
    f = facts(hps=[hp(PD - __import__("datetime").timedelta(days=days))])
    assert check_hp(f).status == status


def test_hp_uses_most_recent_only():
    old, new = hp(date(2026, 1, 1)), hp(date(2026, 3, 20))
    assert check_hp(facts(hps=[old, new])).status == "PASS"
    assert check_hp(facts(hps=[old])).status == "FAIL"


def test_hp_missing_is_fail_and_unverified_is_unknown():
    assert check_hp(facts(hps=[])).status == "FAIL"
    c = check_hp(facts(hps=[hp(PD, verified=False)]))
    assert c.status == "UNKNOWN"


def test_hp_without_procedure_date_is_unknown():
    c = check_hp(facts(procedure_date=None, hps=[hp(date(2026, 3, 1))]))
    assert c.status == "UNKNOWN" and c.unknown_key == "procedure_date"


# --- Rule 1: consent ---------------------------------------------------------

def consent(status, matches=True, verified=True, proc="hernia repair"):
    return ConsentCandidate(status=status, matches_procedure=matches, procedure_named=proc, evidence=ev(), verified=verified)


def test_consent_signed_passes_and_pending_fails():
    assert check_consent(facts(consents=[consent("SIGNED")])).status == "PASS"
    assert check_consent(facts(consents=[consent("PENDING_OR_UNSIGNED")])).status == "FAIL"
    assert check_consent(facts(consents=[])).status == "FAIL"


def test_consent_superseded_and_wrong_procedure():
    assert check_consent(facts(consents=[consent("PENDING_OR_UNSIGNED"), consent("SIGNED")])).status == "PASS"
    c = check_consent(facts(consents=[consent("SIGNED", matches=False, proc="CABG")]))
    assert c.status == "FAIL" and "different procedure" in c.summary


def test_consent_unverified_signature_is_unknown_not_pass():
    assert check_consent(facts(consents=[consent("SIGNED", verified=False)])).status == "UNKNOWN"


# --- Rule 2: labs ------------------------------------------------------------

@pytest.mark.parametrize("risk,days,status", [
    ("LOW", 30, "PASS"), ("LOW", 31, "FAIL"), ("MODERATE", 30, "PASS"), ("MODERATE", 31, "FAIL"),
    ("HIGH", 14, "PASS"), ("HIGH", 15, "FAIL"), ("HIGH", 0, "PASS"),
])
def test_cbc_window_by_risk(risk, days, status):
    from datetime import timedelta
    f = facts(procedure_risk=risk, labs=[lab("CBC", PD - timedelta(days=days))])
    assert check_lab(f, "CBC").status == status


def test_cmp_only_required_for_high():
    assert check_lab(facts(procedure_risk="LOW"), "CMP").status == "NOT_APPLICABLE"
    assert check_lab(facts(procedure_risk="HIGH"), "CMP").status == "FAIL"
    assert check_lab(facts(procedure_risk="HIGH", labs=[lab("CMP", PD)]), "CMP").status == "PASS"


def test_most_recent_lab_only_and_entered_in_error_skipped():
    from datetime import timedelta
    recent_bad = lab("CBC", PD - timedelta(days=1), status="entered-in-error")
    older_ok = lab("CBC", PD - timedelta(days=20))
    c = check_lab(facts(procedure_risk="LOW", labs=[recent_bad, older_ok]), "CBC")
    assert c.status == "PASS" and c.inputs["result_date"] == older_ok.day.isoformat()
    # an in-window old result does not rescue an out-of-window most recent... wait: most recent counts
    c = check_lab(facts(procedure_risk="HIGH", labs=[lab("CBC", PD - timedelta(days=20)), lab("CBC", PD - timedelta(days=40))]), "CBC")
    assert c.status == "FAIL"


def test_lab_after_procedure_date_is_ignored():
    from datetime import timedelta
    c = check_lab(facts(procedure_risk="LOW", labs=[lab("CBC", PD + timedelta(days=1))]), "CBC")
    assert c.status == "FAIL"


def test_bmp_is_not_cmp():
    c = check_lab(facts(procedure_risk="HIGH", labs=[lab("BMP", PD)]), "CMP")
    assert c.status == "FAIL"


def test_missing_risk():
    from datetime import timedelta
    f = facts(procedure_risk=None, labs=[lab("CBC", PD - timedelta(days=20))])
    assert check_lab(f, "CBC").status == "UNKNOWN"          # passes for LOW/MOD, fails HIGH
    assert check_lab(f, "CMP").status == "UNKNOWN"          # only required if HIGH
    f = facts(procedure_risk=None, labs=[])
    assert check_lab(f, "CBC").status == "FAIL"             # fails under every risk
    f = facts(procedure_risk=None, labs=[lab("CBC", PD - timedelta(days=40))])
    assert check_lab(f, "CBC").status == "FAIL"


# --- Rule 3: anticoagulation ------------------------------------------------

def plan(generic, pre=(True, True), post=(True, True), deferred=False, day=date(2026, 3, 1), verified=True):
    def part(p):
        return PlanPartFact(present=p[0], explicit=p[1], evidence=ev() if p[0] else None, verified=verified if p[0] else True)
    return PlanCandidate(generic=generic, drug_as_written=generic, day=day, doc_evidence=ev(quote=None), pre_op=part(pre),
                         post_op=part(post), deferred=deferred, deferral_evidence=None)


def drug(generic, status="CURRENT"):
    return DrugStatus(generic=generic, status=status, evidence=[Evidence(source="medications[0]", value=generic)])


def test_anticoag_not_applicable_when_no_current_drug():
    cs = check_anticoagulation(facts(drugs=[drug("warfarin", "NOT_CURRENT")]))
    assert [c.status for c in cs] == ["NOT_APPLICABLE"]


def test_anticoag_complete_plan_passes():
    cs = check_anticoagulation(facts(drugs=[drug("apixaban")], plans=[plan("apixaban")]))
    assert [c.status for c in cs] == ["PASS"]


@pytest.mark.parametrize("pre,post,deferred", [((True, True), (False, False), False), ((True, True), (True, False), False),
                                               ((False, False), (True, True), False), ((True, True), (True, True), True)])
def test_anticoag_incomplete_plan_fails(pre, post, deferred):
    cs = check_anticoagulation(facts(drugs=[drug("warfarin")], plans=[plan("warfarin", pre, post, deferred)]))
    assert cs[0].status == "FAIL" and cs[0].category == "ANTICOAGULATION_MANAGEMENT"


def test_anticoag_plan_for_other_drug_is_ambiguous_fail():
    cs = check_anticoagulation(facts(drugs=[drug("apixaban")], plans=[plan("rivaroxaban")]))
    assert cs[0].status == "FAIL" and "does not cover the active drug" in cs[0].summary


def test_anticoag_unknown_status_is_unknown():
    cs = check_anticoagulation(facts(drugs=[drug("warfarin", "UNKNOWN")]))
    assert cs[0].status == "UNKNOWN" and cs[0].unknown_key == "anticoagulant_status:warfarin"


def test_anticoag_most_recent_plan_wins():
    old_complete = plan("warfarin", day=date(2026, 2, 1))
    new_incomplete = plan("warfarin", post=(False, False), day=date(2026, 3, 1))
    cs = check_anticoagulation(facts(drugs=[drug("warfarin")], plans=[old_complete, new_incomplete]))
    assert cs[0].status == "FAIL"


def test_anticoag_unverified_plan_quote_is_unknown_not_pass():
    cs = check_anticoagulation(facts(drugs=[drug("warfarin")], plans=[plan("warfarin", verified=False)]))
    assert cs[0].status == "UNKNOWN"


# --- Rule 4: vitals ----------------------------------------------------------

@pytest.mark.parametrize("s,d,status", [(179, 109, "PASS"), (180, 70, "FAIL"), (150, 110, "FAIL"), (179, 110, "FAIL"), (181, 95, "FAIL")])
def test_bp_boundaries(s, d, status):
    assert check_vital(facts(readings=[bp(s, d)]), "BP").status == status


@pytest.mark.parametrize("t,status", [(100.4, "PASS"), (100.5, "FAIL"), (98.6, "PASS"), (101.48, "FAIL")])
def test_temp_boundaries(t, status):
    assert check_vital(facts(readings=[temp(t)]), "TEMP").status == status


def test_most_recent_vital_and_recheck_clears():
    old_high = bp(190, 120, day=date(2026, 3, 20))
    recheck = bp(130, 80, day=date(2026, 3, 21))
    assert check_vital(facts(readings=[old_high, recheck]), "BP").status == "PASS"
    assert check_vital(facts(readings=[recheck, bp(185, 80, day=date(2026, 3, 22))]), "BP").status == "FAIL"


def test_same_day_recheck_with_times_uses_latest_time():
    first = bp(189, 112, day=PD, clock=time(8, 6))
    addendum = bp(137, 78, day=PD, clock=time(8, 30))
    assert most_recent_reading([first, addendum]) is addendum


def test_same_day_tie_without_time_is_conservative():
    with_time = bp(120, 80, day=PD, clock=time(10, 0))
    no_time = bp(185, 90, day=PD, clock=None)
    assert most_recent_reading([with_time, no_time]) is no_time
    assert check_vital(facts(readings=[with_time, no_time]), "BP").status == "FAIL"


def test_missing_vitals_are_unknown_not_pass():
    c = check_vital(facts(readings=[]), "TEMP")
    assert c.status == "UNKNOWN" and c.unknown_key == "temperature"
    c = check_vital(facts(readings=[bp(200, 120, verified=False)]), "BP")
    assert c.status == "UNKNOWN"


# --- Decision precedence -----------------------------------------------------

def test_precedence_not_cleared_beats_follow_up_and_reports_all_issues():
    f = facts(readings=[bp(190, 80), temp(98.6)], hps=[], consents=[consent("SIGNED")], labs=[lab("CBC", PD)])
    checks = run_all_checks(f)
    decision, _ = decide(checks)
    assert decision == "NOT_CLEARED"
    cats = {i.category for i in build_issues(checks)}
    assert cats == {"ACUTE_SAFETY_EXCLUSION", "REQUIRED_DOCUMENTATION"}


def test_unknown_yields_follow_up_and_missing_data_category():
    f = facts(procedure_risk=None, readings=[bp(120, 80), temp(98.6)], hps=[hp(PD)], consents=[consent("SIGNED")], labs=[lab("CBC", PD), lab("CMP", PD)])
    checks = run_all_checks(f)
    assert decide(checks)[0] == "NEEDS_FOLLOW_UP"
    issues = build_issues(checks)
    assert [i.category for i in issues] == ["MISSING_REQUIRED_DATA"]


def test_missing_procedure_date_is_single_missing_data_issue():
    f = facts(procedure_date=None, procedure_date_source=None, readings=[bp(120, 80), temp(98.6)], hps=[hp(date(2026, 3, 1))],
              consents=[consent("SIGNED")], labs=[lab("CBC", date(2026, 3, 1))])
    checks = run_all_checks(f)
    issues = build_issues(checks)
    assert decide(checks)[0] == "NEEDS_FOLLOW_UP"
    assert [i.category for i in issues] == ["MISSING_REQUIRED_DATA"]


def test_all_pass_is_ready_with_evidence_on_every_check():
    f = facts(readings=[bp(120, 80), temp(98.6)], hps=[hp(PD)], consents=[consent("SIGNED")], labs=[lab("CBC", PD)])
    checks = run_all_checks(f)
    assert decide(checks)[0] == "READY"
    assert build_issues(checks) == []
    for c in checks:
        if c.status == "PASS" and c.rule != "REFERENCE":
            assert c.evidence, c.name
