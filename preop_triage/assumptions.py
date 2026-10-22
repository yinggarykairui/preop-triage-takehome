"""Numbered policy-interpretation assumptions.

Every place in the code that relies on one of these cites its ID, and the
evidence packet lists the IDs that were actually applied to a case. The same
list appears in WRITEUP.md.
"""

ASSUMPTIONS: dict[str, str] = {
    "A1": "All timestamps are treated as UTC and reduced to calendar dates; windows are whole-day counts.",
    "A2": "'Within N days' is inclusive: 0 <= procedure_date - item_date <= N. Day 30 passes, day 31 fails; day 14 passes, day 15 fails.",
    "A3": "Items dated after the procedure date are not pre-operative and are excluded; the most recent qualifying item on or before the procedure date is used.",
    "A4": "Procedure date: the structured field wins; if null, a date explicitly stated as the scheduled/target procedure date in the documents is used only when every stated date agrees, no document says the date is still TBD/pending, and the date is not earlier than the document stating it. Otherwise -> unknown -> MISSING_REQUIRED_DATA, and the window checks that depend on it are folded into that single issue.",
    "A5": "Procedure risk comes only from the structured field. Missing or not LOW/MODERATE/HIGH -> MISSING_REQUIRED_DATA. Testing checks still FAIL when they fail under every possible risk (e.g. no CBC at all) and PASS only when they pass under every risk.",
    "A6": "Rule 4 review time is metadata.submission_received_at (falls back to the latest vital). Readings are not discarded for age; the most recent reading per vital type is used.",
    "A7": "Vitals come from the structured list and from free text (nursing/intake notes, H&P exam lines). 'See flowsheet', deferred vitals and patient-reported home logs are not readings. A text reading carries the document date plus the clock time if the note states one.",
    "A8": "Most-recent vital tie-break: order by date then time. If the latest-dated readings include one without a time, or share the same time, the more abnormal reading wins (conservative).",
    "A9": "No reading at all for a required vital (BP or temperature) -> unknown -> MISSING_REQUIRED_DATA, never READY.",
    "A10": "Temperatures in Celsius are converted (F = C*9/5 + 32) before the strict > 100.4 F comparison.",
    "A11": "CBC/CMP are recognized from code and display ('Hemogram/CBC', 'CBC w/ Differential', 'LAB-CMP', 'CMP w/ Magnesium'); a BMP is never a CMP. Only status final/corrected/amended counts; entered-in-error, cancelled, preliminary results are skipped and the next most recent qualifying result is used.",
    "A12": "A document is an H&P when its text is an H&P, regardless of the type label; notes that merely reference an H&P ('not on file') are not H&Ps. The most recent completed H&P is checked, dated by its stated date of service, else the document date. Whether it is specifically a pre-op evaluation is reported but not required.",
    "A13": "Consent passes only with a consent signed by the patient (a physician attestation alone is not a signature) for the planned procedure. A signed consent is not invalidated by another pending/unsigned form; a signed consent for a different procedure does not count.",
    "A14": "Anticoagulants: warfarin, apixaban, rivaroxaban, dabigatran, edoxaban, betrixaban, enoxaparin, dalteparin, fondaparinux, heparin (brand names mapped to generics). Antiplatelets (aspirin, clopidogrel, ticagrelor, prasugrel, dipyridamole) are not anticoagulants.",
    "A15": "'Currently taking' is resolved from the med list plus notes: active=true -> current; active=false -> not current unless the most recent note says current (conflict -> unknown); active=null -> the most recent note decides, else unknown; a drug a note says the patient currently takes counts even if absent from the list. Unknown status -> MISSING_REQUIRED_DATA.",
    "A16": "A plan is complete only if the most recent plan document naming the current drug (brand/generic equivalence applied) gives an explicit pre-op instruction (hold/stop with timing) AND an explicit post-op instruction (resume/restart timing or bridge). Deferrals ('to be determined by the surgical team', 'will be addressed after surgery') and plans naming a different drug are incomplete/ambiguous -> ANTICOAGULATION_MANAGEMENT.",
    "A17": "Fail-safe: an LLM error, schema failure or unverifiable quote degrades the affected fact to unknown. Unknown facts can turn a PASS into UNKNOWN but never a FAIL into PASS; any UNKNOWN check yields NEEDS_FOLLOW_UP.",
    "A18": "Category string is ANTICOAGULATION_MANAGEMENT; the PDF's 'ANTICOAGULATION_MANAGEMENTJSON' is a PDF extraction artifact (the harness Literal and labels use the former).",
    "A19": "Issues: one per failing sub-check; unknowns are reported as MISSING_REQUIRED_DATA, one per missing datum. A NOT_CLEARED patient still lists every follow-up issue.",
}
