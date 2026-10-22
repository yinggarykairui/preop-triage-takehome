# Pre-Op Scheduling Triage: approach and results

## 1. Problem framing

Each submission is a small FHIR-like bundle (structured procedure/vitals/labs/meds plus 3–8
free-text documents of up to ~2,200 characters). The policy has four rules and three statuses.
The data profile (`notes/data_profile.md`) showed where the difficulty actually is:

- The structured fields are not the truth. 48/50 cases carry blood pressures in note text, 10 carry
  temperatures in °C, 28 notes say "see flowsheet", 39 distinct `documents[].type` strings cover
  the same handful of real document kinds, and the H&P title is sometimes misspelled.
- Deciding facts live only in text: pending signatures, consents for a different operation, "H&P not
  on file", anticoagulants reported at intake but absent from the med list, perioperative plans that
  defer the post-op side, procedure dates that are "pending OR availability".
- The asymmetry of errors is extreme: a false READY sends an unreviewed patient to the OR, while a
  false NEEDS_FOLLOW_UP costs a nurse a minute. The design has to make the safe direction the
  default whenever the system is unsure.

The baseline (one prompt, one model call that both reads and decides) scored 73.3% on the harness
with 70% decision accuracy, 52% category accuracy, and one false READY (case_00026, a missing CBC).
Its failure mode is the expected one: a single call has to be right about everything at once, cannot
show its work, and is not deterministic.

## 2. Architecture: the LLM extracts, code decides

```
raw JSON ─► normalize (code) ─► extract facts (LLM, structured, per document, 2 extractors)
         ─► verify quotes (code) ─► rule engine (pure functions) ─► decision + evidence packet
```

**Normalize (code, `normalize.py`).** Dates to UTC calendar days; °C→°F; lab canonicalization from
`code` *and* `display` ("Hemogram/CBC", "LAB-CMP … w/ Magnesium" count; "BMP" never equals "CMP");
drug brand→generic with an explicit antiplatelet exclusion list; the most-recent-reading selector
with a conservative tie-break.

**Extract (LLM, `extract.py`).** Two extractors run on every document with strict JSON-schema
outputs at temperature 0: *document facts* (what the text really is, H&P completion date, consent
signature status and the procedure it names, a stated procedure date, every measured BP/temperature
with its clock time, "vitals deferred" flags) and *anticoagulation facts* (per-drug "currently
taking" status as of that note, and the plan's pre-op / post-op parts with an `explicit` flag and a
deferral flag). The second extractor only runs on documents whose text matches a broad
anticoagulation regex, which is a code-side guard rather than an LLM judgement. Each extractor sees
one document plus the planned procedure name; it never sees the policy and is never asked for a
decision. Per-document calls keep each prompt small, make the cache granular, and allow parallelism.

**Verify (code, `verify.py`).** Every positive claim must carry a quote, and every quote must be an
exact or whitespace/unicode-normalized substring of the cited document. A failing quote triggers one
repair call that lists the offending quotes; anything still unverified is kept only as an *unverified*
fact. The rule engine treats unverified facts asymmetrically: they can turn a PASS into UNKNOWN but
can never produce a PASS. This is the anti-hallucination guard, and the extraction fixture test
asserts that every reading driving a decision was verified.

**Rule engine (code, `rules.py`).** One pure function per sub-rule (H&P window, signed consent,
CBC, CMP, anticoagulation plan per current drug, BP, temperature, plus procedure-date and risk
reference checks). Each returns a `Check` with `PASS | FAIL | UNKNOWN | NOT_APPLICABLE`, the inputs
it used (dates, day deltas, thresholds), the reference dates, the evidence and the assumption IDs it
relied on. Precedence: any `ACUTE_SAFETY_EXCLUSION` FAIL → `NOT_CLEARED`; otherwise any FAIL or
UNKNOWN → `NEEDS_FOLLOW_UP`; otherwise `READY`. A NOT_CLEARED patient still lists every follow-up
issue. The engine is covered by 74 tests that never touch the LLM.

**Fail-safe.** Any provider error, timeout or schema failure is caught in `llm.py` and recorded; the
affected document becomes "unreadable", which is itself an UNKNOWN check, so the case degrades to
NEEDS_FOLLOW_UP with a `MISSING_REQUIRED_DATA` issue naming the document. `tests/test_extraction_fixtures.py`
proves that a dead provider yields NEEDS_FOLLOW_UP, never READY.

**Reproducibility.** Provider and model are configurable; responses are cached on disk keyed by a hash
of (provider, model, prompt, schema). The cache is committed, so `make baseline`, `make summary`,
`make determinism` and the tests run without an API key, and the determinism check is trivially 100%.

Why this split: the policy is a small decision table, and decision tables belong in code where they
can be unit-tested at their boundaries (179/180, day 30/31), audited, and changed without re-prompting.
What is genuinely hard, reading messy clinical prose, is the only part delegated to the model, and
even there the model is constrained to point at text we can check.

## 3. The evidence packet, designed for the nurse

A pre-op nurse reviews every non-READY case and a sample of READY ones, so the packet is built
around two questions: *what blocks this patient, and how do I confirm it in under a minute?*

- `decision_rationale`: one sentence naming the deciding rule(s).
- `reference_dates`: the procedure date, where it came from (structured field or a `doc_id` + quote),
  the risk category, and the review time, because every window hinges on these.
- `issues[]`: category, rule, a one-line summary, a concrete `resolution` ("Obtain a plan naming
  apixaban with pre-op hold and post-op resumption instructions"), and `evidence[]` where each item
  is either a structured field path (`labs[2]`, `medications[1]`, `procedure.procedure_risk`) or a
  `doc_id` + `doc_type` + `date` + verbatim `quote` with a `verified` flag. No prose evidence without a
  pointer.
- `checks[]`: every rule including the PASSes, with the inputs used ("CBC 2026-02-11, 18 days before,
  limit 30"), so a sampled READY case is auditable without re-reading the chart.
- `assumptions_applied`: the IDs of the interpretations that were exercised, which lets a reviewer
  disagree with an interpretation rather than with the system.
- `meta`: model, pipeline version, LLM failures and unverified-quote counts, so an operator can tell a
  clean run from a degraded one.

`view_report.py` renders all of this in the provided TUI (issues with evidence pointers, the full
check list with PASS/FAIL/UNKNOWN colouring, reference dates, assumptions, meta).

## 4. Assumptions (numbered; cited by checks and packets)

(Source of truth: `preop_triage/assumptions.py`.)

- **A1.** All timestamps are treated as UTC and reduced to calendar dates; windows are whole-day counts.
- **A2.** 'Within N days' is inclusive: 0 <= procedure_date - item_date <= N. Day 30 passes, day 31 fails; day 14 passes, day 15 fails.
- **A3.** Items dated after the procedure date are not pre-operative and are excluded; the most recent qualifying item on or before the procedure date is used.
- **A4.** Procedure date: the structured field wins; if null, a date explicitly stated as the scheduled/target procedure date in the documents is used only when every stated date agrees, no document says the date is still TBD/pending, and the date is not earlier than the document stating it. Otherwise -> unknown -> MISSING_REQUIRED_DATA, and the window checks that depend on it are folded into that single issue.
- **A5.** Procedure risk comes only from the structured field. Missing or not LOW/MODERATE/HIGH -> MISSING_REQUIRED_DATA. Testing checks still FAIL when they fail under every possible risk (e.g. no CBC at all) and PASS only when they pass under every risk.
- **A6.** Rule 4 review time is metadata.submission_received_at (falls back to the latest vital). Readings are not discarded for age; the most recent reading per vital type is used.
- **A7.** Vitals come from the structured list and from free text (nursing/intake notes, H&P exam lines). 'See flowsheet', deferred vitals and patient-reported home logs are not readings. A text reading carries the document date plus the clock time if the note states one.
- **A8.** Most-recent vital tie-break: order by date then time. If the latest-dated readings include one without a time, or share the same time, the more abnormal reading wins (conservative).
- **A9.** No reading at all for a required vital (BP or temperature) -> unknown -> MISSING_REQUIRED_DATA, never READY.
- **A10.** Temperatures in Celsius are converted (F = C*9/5 + 32) before the strict > 100.4 F comparison.
- **A11.** CBC/CMP are recognized from code and display ('Hemogram/CBC', 'CBC w/ Differential', 'LAB-CMP', 'CMP w/ Magnesium'); a BMP is never a CMP. Only status final/corrected/amended counts; entered-in-error, cancelled, preliminary results are skipped and the next most recent qualifying result is used.
- **A12.** A document is an H&P when its text is an H&P, regardless of the type label; notes that merely reference an H&P ('not on file') are not H&Ps. The most recent completed H&P is checked, dated by its stated date of service, else the document date. Whether it is specifically a pre-op evaluation is reported but not required.
- **A13.** Consent passes only with a consent signed by the patient (a physician attestation alone is not a signature) for the planned procedure. A signed consent is not invalidated by another pending/unsigned form; a signed consent for a different procedure does not count.
- **A14.** Anticoagulants: warfarin, apixaban, rivaroxaban, dabigatran, edoxaban, betrixaban, enoxaparin, dalteparin, fondaparinux, heparin (brand names mapped to generics). Antiplatelets (aspirin, clopidogrel, ticagrelor, prasugrel, dipyridamole) are not anticoagulants.
- **A15.** 'Currently taking' is resolved from the med list plus notes: active=true -> current; active=false -> not current unless the most recent note says current (conflict -> unknown); active=null -> the most recent note decides, else unknown; a drug a note says the patient currently takes counts even if absent from the list. Unknown status -> MISSING_REQUIRED_DATA.
- **A16.** A plan is complete only if the most recent plan document naming the current drug (brand/generic equivalence applied) gives an explicit pre-op instruction (hold/stop with timing) AND an explicit post-op instruction (resume/restart timing or bridge). Deferrals ('to be determined by the surgical team', 'will be addressed after surgery') and plans naming a different drug are incomplete/ambiguous -> ANTICOAGULATION_MANAGEMENT.
- **A17.** Fail-safe: an LLM error, schema failure or unverifiable quote degrades the affected fact to unknown. Unknown facts can turn a PASS into UNKNOWN but never a FAIL into PASS; any UNKNOWN check yields NEEDS_FOLLOW_UP.
- **A18.** Category string is ANTICOAGULATION_MANAGEMENT; the PDF's 'ANTICOAGULATION_MANAGEMENTJSON' is a PDF extraction artifact (the harness Literal and labels use the former).
- **A19.** Issues: one per failing sub-check; unknowns are reported as MISSING_REQUIRED_DATA, one per missing datum. A NOT_CLEARED patient still lists every follow-up issue.

## 5. Results

RESULTS_PLACEHOLDER

## 6. Error analysis

ERROR_ANALYSIS_PLACEHOLDER

## 7. Known limitations

- **Sample size.** 50 labelled cases, synthetic and fairly templated. The rule engine is tested at its
  boundaries, but the extractors have only been exercised on this distribution of note styles.
- **Extraction is still an LLM.** Quote verification guarantees that cited text exists, not that it was
  interpreted correctly (e.g. whether a consent's procedure "matches" the planned one is the model's
  judgement). Negative claims (NOT_A_CONSENT, no vitals) carry no quote and cannot be verified; a
  missed reading can only be caught by a later reading or by a nurse.
- **Procedure-date fallback.** When the structured date is null the pipeline accepts a date stated in
  the documents only if every stated date agrees; a confidently wrong date in an H&P would be used.
- **Anticoagulation plan semantics** are reduced to pre-op present/explicit, post-op present/explicit,
  deferred, and drug match. Dose-level correctness is out of scope by policy and by design.
- **Tie-breaks and staleness.** The conservative same-day tie-break (A8) can hold a patient on an
  older abnormal reading when the recheck time is not recorded; the policy says nothing about how
  old a vital may be, so none is enforced (A6).
- **Latency/cost.** ~5–9 calls per case with gpt-4.1-mini; a cold run of 50 cases takes several
  minutes. Cached reruns are instant.

## 8. What I would do next

1. **Confidence-based routing.** Attach a confidence to each check (unverified quotes, repair retries,
   disagreements between the two extractors or between the med list and notes) and route low-confidence
   READYs to the nurse sample instead of sampling uniformly.
2. **A larger, adversarial eval set.** Mutate the 50 cases systematically (shift dates across each
   boundary, flip units, move facts between structured fields and text, rename document types,
   inject conflicting notes) to measure extractor recall per fact type rather than overall accuracy.
3. **Production monitoring of false READYs.** Log every packet; reconcile READY decisions against the
   nurse's final disposition and day-of-surgery cancellations; alert on any false READY, and track the
   UNKNOWN rate per missing-datum key as a data-quality signal for the intake feed.
4. **Two-model agreement on safety facts.** Run the vitals/consent extractors with a second model (or a
   second prompt) and treat disagreement as UNKNOWN.
5. **Cheaper reading.** Many documents are templated (nutrition, PT, portal messages); a small
   classifier could skip them, and a regex pre-pass could cover the structured vitals lines so the LLM
   only handles the irregular prose.
