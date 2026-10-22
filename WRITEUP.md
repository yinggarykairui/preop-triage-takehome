# Pre-Op Scheduling Triage: approach and results

**TL;DR**

- **Approach:** the LLM only *reads*. Two per-document extractors return strict-schema facts with verbatim quotes; code verifies every quote against the document, then a pure rule engine applies the four policy rules and emits a decision plus an auditable evidence packet.
- **Headline results (50 labelled cases, gpt-4.1-mini):** naive single-call baseline 73.3% on the harness (decision 70%, categories 52%, 1 false READY). Final pipeline 100% on all three metrics, 0 false READYs, deterministic 10/10 replays.
- **Key design choice:** an unverifiable or missing fact can only move a check toward UNKNOWN, never toward PASS, so every failure mode of the model degrades to NEEDS_FOLLOW_UP instead of a false READY.
- **Depth:** a seeded perturbation suite of 170 mutations whose answers follow from the policy by construction (window edges, vital thresholds in °F and °C, rechecks, brand/generic swaps, pending consents, deferred plans, missing dates and risk) passes 170/170; an ablation shows the fail-safe is what prevents false READYs (5 on the sample, 6 on the perturbations without it).
- **Honesty:** the 100% on the labelled set is in-sample. Labels were visible while iterating; the first full run scored 98.0% and two prompts were revised after error analysis. No label disagreements were found.
- **Everything replays from a committed cache**, so tests, the full run, the local scorer and the determinism check run from a clean clone without an API key in a few seconds.

## 1. Problem and data

Each submission is a small FHIR-like bundle (structured procedure, vitals, labs, meds, plus 3–8
free-text documents of up to 2,200 characters). The policy has four rules and three statuses.
Profiling the sample ([notes/data_profile.md](notes/data_profile.md)) showed where the difficulty is:

- **The structured fields are not the truth.** 48/50 cases carry blood pressures in note text, 10 carry
  temperatures in °C, 28 notes say "see flowsheet", and 39 distinct `documents[].type` strings label
  the same handful of real document kinds (the H&P title is sometimes misspelled).
- **The deciding facts live in prose:** pending signatures, consents for a different operation, "H&P not
  on file", anticoagulants reported at intake but absent from the med list, perioperative plans that
  defer the post-op side, procedure dates that are "pending OR availability".
- **Errors are asymmetric.** A false READY sends an unreviewed patient to the OR; a false
  NEEDS_FOLLOW_UP costs a nurse a minute. The safe direction has to be the default whenever the
  system is unsure.

The naive baseline (one prompt, one call that reads and decides) fails the way one would expect: it
invents criteria (A1c, CMP for low risk), reports a category per observation instead of per failed
rule, produced one invalid JSON, one false READY on a missing CBC, and is not stable run to run.

## 2. Architecture

```
raw JSON ─► normalize (code) ─► extract facts (LLM, strict schema, per document, 2 extractors)
         ─► verify quotes (code) ─► rule engine (pure functions) ─► decision + evidence packet
```

| stage | module | what it does |
|---|---|---|
| Normalize | `normalize.py` | dates → UTC calendar days; °C→°F; lab canonicalization from `code` *and* `display` ("Hemogram/CBC", "LAB-CMP … w/ Magnesium"; BMP ≠ CMP); drug brand→generic with an explicit antiplatelet exclusion; most-recent-reading selector with a conservative tie-break |
| Extract | `extract.py`, `schemas.py` | **Document facts** (what the text really is, H&P date, consent signature status and the procedure it names, a stated procedure date, every measured BP/temperature with clock time) and **anticoagulation facts** (per-drug "currently taking" status; the plan's pre-op and post-op parts with `explicit` and `deferred` flags). The second extractor runs only on documents matching an anticoagulation regex. Each call sees one document plus the planned procedure name; it never sees the policy and is never asked for a decision. Temperature 0, strict JSON schema. |
| Verify | `verify.py` | every positive claim must quote the document; the quote must be an exact, whitespace/unicode-normalized, or punctuation-insensitive substring with every digit intact. One repair call lists failed quotes; what still fails stays *unverified* and can only weaken a decision |
| Rules | `rules.py` | one pure function per sub-rule (H&P window, signed consent, CBC, CMP, plan per current anticoagulant, BP, temperature, plus procedure-date and risk reference checks). Each returns a `Check` with `PASS / FAIL / UNKNOWN / NOT_APPLICABLE`, the inputs it used, evidence, and the assumption IDs it relied on. Precedence: any safety FAIL → NOT_CLEARED; else any FAIL or UNKNOWN → NEEDS_FOLLOW_UP; else READY |
| Fail-safe | `llm.py`, `rules.check_extraction` | provider error, timeout or schema failure marks the document unreadable, which is itself an UNKNOWN check → NEEDS_FOLLOW_UP + MISSING_REQUIRED_DATA naming the document |
| Reproducibility | `llm.py` | responses cached on disk keyed by sha256(provider, model, prompt, schema); the cache is committed |

**Why this split.** The policy is a small decision table, and decision tables belong in code where
they can be unit-tested at their boundaries (day 30/31, 179/180), audited, and changed without
re-prompting. Reading messy clinical prose is the only genuinely hard part, so it is the only part
delegated to a model, and even there the model must point at text the code can check.

**The evidence packet** is built for the nurse who reviews every non-READY case and samples READY
ones: `decision_rationale` (one sentence naming the deciding rules), `reference_dates` (procedure date
and where it came from, risk, review time), `issues[]` (category, rule, summary, a concrete
`resolution`, and `evidence[]` where each item is a structured field path or a `doc_id` + verbatim
`quote` + `verified` flag), `checks[]` (every rule including PASSes, with the inputs used, so a sampled
READY is auditable without re-reading the chart), `assumptions_applied`, and `meta` (model, failures,
unverified-quote counts). `view_report.py` renders all of it; the schema is in README.

## 3. Assumptions

Nineteen numbered interpretations, each cited by the checks that rely on it and each pointing to the
function that enforces it. Full text and code pointers: [notes/assumptions.md](notes/assumptions.md)
(generated from `preop_triage/assumptions.py`; a test fails if either drifts). The ones that decide cases:

| ID | interpretation | enforced in |
|---|---|---|
| A2 | windows are inclusive whole days: day 30 passes, day 31 fails | `normalize.within_window` |
| A4 | procedure date: structured field, else a stated scheduled date only if all stated dates agree, none says TBD, and it is not before its own document; otherwise unknown → one MISSING_REQUIRED_DATA issue that absorbs the window checks | `pipeline._procedure_date` |
| A5 | risk comes only from the structured field; with risk unknown a lab check still FAILs if it fails under every risk (no CBC at all) and PASSes only if it passes under every risk | `rules.check_lab` |
| A7, A9 | vitals in note text count (H&P exam lines, nursing addenda); "see flowsheet" and home readings do not; no reading at all → MISSING_REQUIRED_DATA, never READY | `pipeline._readings`, `rules.check_vital` |
| A8 | same-day readings with a missing or equal clock time: the more abnormal wins | `normalize.most_recent_reading` |
| A11 | only final/corrected/amended labs count; entered-in-error is skipped and the next most recent used | `rules._latest_lab` |
| A12 | any document whose *text* is an H&P counts (incl. wellness/establish-care); "H&P not on file" references do not | `pipeline._hps` |
| A13 | consent needs the patient's signature for the planned procedure; a later signed consent supersedes a pending one; signed-for-another-procedure fails | `rules.check_consent` |
| A15 | "currently taking" = med list `active`, resolved by the most recent note when the flag is null or absent; a note saying the patient takes a drug missing from the list makes it current | `pipeline._drugs` |
| A16 | a plan is complete only if the most recent plan naming the current drug has explicit pre-op *and* post-op instructions and no deferral | `rules.check_anticoagulation` |
| A17 | unverified facts and LLM failures can lower a check to UNKNOWN but never raise one to PASS | `verify`, `llm`, `rules.decide` |

## 4. Results

Official reports from the provided `run_evals.py`: `results/baseline_eval_report.json` (73.33) and
`results/final_eval_report.json` (100.0). `scripts/score_local.py` reproduces the same metrics
locally and adds the confusion matrix (`results/*_summary.md`). Model: gpt-4.1-mini throughout.

| metric | naive baseline | pipeline run 1 | final pipeline |
|---|---|---|---|
| json_schema_valid | 98.0% | 100% | 100% |
| decision_match_oracle | 70.0% | 98.0% | 100% |
| issue_categories_match_oracle | 52.0% | 96.0% | 100% |
| **aggregate (harness primary score)** | **73.33%** | **98.0%** | **100.0%** |
| false READYs | 1 (case_00026) | 0 | 0 |
| determinism (10× replay, record 0) | unstable | — | 100% decision / JSON / exact output |

Decision confusion (rows = label, columns = predicted). Baseline: READY 6/11/0, NEEDS_FOLLOW_UP
1/24/0, NOT_CLEARED 0/2/5 (+1 invalid). Final: diagonal 17 / 25 / 8.
Per-category issue precision and recall (final): 100% / 100% for all five categories
(12 REQUIRED_DOCUMENTATION, 7 REQUIRED_TESTING, 7 ANTICOAGULATION_MANAGEMENT, 8 ACUTE_SAFETY_EXCLUSION,
9 MISSING_REQUIRED_DATA labelled occurrences). Baseline per-category numbers: `results/baseline_summary.md`.

**Verification telemetry (final):** the live run made 342 calls with 0 provider failures. Replaying
from the committed cache touches 326 cached responses (fewer repair calls are triggered after the
verifier hardening below) and leaves 2 unverified quotes in 50 cases, both correct rejections
(a spliced quote and a unit-less quote) with no decision impact.

**Cost and latency:** ~6.5 calls per case; a cold run of 50 cases is roughly 15–25 minutes and about
$0.40 at list prices; the cached replay takes 2 seconds.

### 4.1 Perturbation suite ([results/perturbation.md](results/perturbation.md), `make perturb`)

`eval/perturb.py` takes sample cases that satisfy a precondition and applies a seeded mutation whose
effect on the decision and categories is known from the policy alone, so the suite measures the
pipeline rather than the labeler. Structured mutations leave document text untouched and replay the
cache; three families rewrite a document and run through the LLM (their responses are cached too).

| family | mutation | n | pass |
|---|---|---|---|
| hp_window | H&P at day 30 vs 31 (procedure date, labs and vitals shifted together) | 12 | 12 |
| cbc_window, cmp_window | single CBC at 30/31 or 14/15; risk forced HIGH with CMP at 14/15 | 24 | 24 |
| lab_entered_in_error, risk_upgrade | newer entered-in-error CBC must be skipped; LOW→HIGH pushes a day-15–30 CBC out of window | 18 | 18 |
| bp_threshold, temp_threshold_f, temp_threshold_c | 179/180, 109/110, 100.4/100.5 °F, 38.0/38.1 °C as structured vitals | 48 | 48 |
| bp_recheck | 185/95 then 128/78 (READY) and the reverse (NOT_CLEARED), list order varied | 18 | 18 |
| anticoag_brand_generic, anticoag_wrong_drug | Xarelto↔rivaroxaban etc. must not change the outcome; list drug the plan does not name must fail | 10 | 10 |
| plan_no_postop, consent_pending, temp_threshold_c_text (LLM) | post-op line replaced by a deferral; signature line set to pending; "Temp 38.0/38.1 °C" addendum appended | 22 | 22 |
| null_procedure_date, missing_risk | date only in note text (A4 fallback → READY); risk null with and without any CBC (A5) | 18 | 18 |
| **total** | | **170** | **170 (100%), 0 false READYs** |

Building the suite found one real bug: the provided input schema had no `value_c` on temperature
vitals, so a structured Celsius temperature was silently dropped before the pipeline (which already
handled it) saw it. Fixed in `core.py`; `temp_threshold_c` now covers it.

### 4.2 Ablation ([results/ablation.md](results/ablation.md), `make ablation`)

`TRIAGE_ABLATE` turns off quote verification (`no_verify`: every quote accepted, no repair retry) and
the fail-safe (`no_failsafe`: UNKNOWN checks neither block clearance nor raise MISSING_REQUIRED_DATA).
Accuracy is the harness aggregate.

| variant | sample accuracy | sample false READYs | perturbation accuracy | perturbation false READYs |
|---|---|---|---|---|
| full pipeline | 100.0% | 0 | 100.0% | 0 |
| no quote verification | 100.0% | 0 | 100.0% | 0 |
| no fail-safe | 90.7% | **5** | 96.5% | **6** |
| neither | 90.7% | 5 | 96.5% | 6 |

The fail-safe is load-bearing: without it, every case whose temperature, risk, procedure date or
anticoagulant status is unknown is cleared. Quote verification changed no decision on this data: all
70 quotes it rejected across the three runs were correct rejections of facts that had no decision
impact, which says the extractor did not hallucinate a decision-relevant fact here, not that it never
will. Its value is as a guard against a failure mode this synthetic data does not contain.

## 5. Error analysis

Full detail in [notes/error_analysis.md](notes/error_analysis.md). Fixes were always to the general
cause; no case IDs appear in the code.

- **Extraction (2 misses in run 1, both fixed).**
  (i) With the structured procedure date null, the extractor returned a consent's *signature* date as
  the procedure date, so the CBC window ran and failed. Fix: the prompt defines a procedure date as an
  explicit scheduled/target date and excludes signature, visit, service and lab dates; code rejects a
  stated date earlier than its own document and treats any verified "TBD" statement as a conflict (A4).
  (ii) The anticoagulation extractor took an H&P line ("continue home medications except as directed
  by perioperative instructions") as a perioperative plan for Xarelto; being newer, it shadowed the
  real plan. Fix: a plan must give recommendations for a *named* anticoagulant and the generic pattern
  is called out as not-a-plan; when a later note supersedes an earlier complete plan, both are cited.
- **Normalization (0 misses; 68 → 2 unverified quotes).** The model writes `°F` as a control character
  plus "6" and sometimes drops parentheses; those quotes were rejected and the facts dropped. The
  verifier now strips control characters (with the character they garbled) and degree signs and has a
  punctuation-insensitive tier that keeps every digit exact. A paraphrased "vitals not recorded" quote
  (52 occurrences, no decision impact) was removed by requiring the quoted phrase.
- **Rule interpretation (0 misses).** The boundary cases present in the data (H&P at day 30 and 31,
  CBC at day 15 for HIGH risk, DBP exactly 110, 37.9 °C = 100.2 °F) all resolve under A2/A10 as labelled.
- **Label disagreement (0).** No label contradicts the policy. Four places where a different reading was
  defensible (missing temperature → MISSING_REQUIRED_DATA; note-reported anticoagulants count;
  establish-care H&Ps count; a null procedure date does not also fail documentation/testing) are
  spelled out in the notes; in each the labels agree with the safer reading.

## 6. Depth and validation

- **90 tests, none touching the network** (`make test`, ~2 s). 50 rule-engine tests at the boundaries
  (179/180, 109/110, 100.4/100.5, day 30/31, 14/15), precedence, tie-breaks, entered-in-error labs,
  missing date/risk, plan completeness. 25 normalization/verifier tests, including mojibake and
  altered-digit rejection. 3 extraction-fixture tests run the real extractors against a committed cache
  and assert that every reading driving the decision was verified, and that a dead provider yields
  NEEDS_FOLLOW_UP, never READY. 3 tests keep the assumption list, the code and `notes/assumptions.md`
  in sync; 6 cover the ablation switches and the perturbation generator (seeded, well-formed, structured
  mutations never touch documents).
- **Perturbation and ablation** (§4.1–4.2): 170 constructed mutations pass; removing the fail-safe produces
  false READYs on both sets.
- **Determinism:** `make determinism` replays record 0 ten times through `triage_submission`: 100%
  decision, JSON and exact-output stability (temperature 0 plus the cache make this structural).
- **Reproducibility:** the clean-clone replay reproduces every committed packet byte for byte apart from
  call counters.
- **Auditability:** each packet lists every check, its inputs and evidence, and the assumption IDs used;
  the TUI (`make report`) shows them per case next to the labeler's rationale.

## 7. Limitations

- **Sample size and in-sample tuning.** 50 synthetic, fairly templated cases; two prompts were revised
  after seeing misses. The engine is tested at its boundaries, but extractor recall is only known on
  this distribution of note styles.
- **Extraction is still an LLM.** Verification guarantees a quoted string exists, not that it was
  interpreted correctly (e.g. whether a consent's procedure "matches" the planned one). Negative claims
  (NOT_A_CONSENT, "no vitals here") carry no quote and cannot be verified; a missed reading is caught
  only by another reading or by the nurse.
- **Procedure-date fallback.** With the structured date null, a single confidently wrong date stated in
  an H&P would be used if nothing contradicts it.
- **Plan semantics are coarse:** pre-op present/explicit, post-op present/explicit, deferred, drug match.
  Dose-level correctness is out of scope by policy.
- **Staleness is not enforced** (the policy sets no maximum vital age, A6), and the conservative
  same-day tie-break (A8) can hold a patient on an older abnormal reading when a recheck has no time.
- **One provider.** Only OpenAI is implemented behind the `Provider` protocol.
- **Perturbations cover structured fields far better than prose.** 148 of the 170 mutations change
  structured fields; only three families rewrite document text. Renamed document types, conflicting notes
  and moved facts (structured → text) are not yet exercised, and the ablation shows verification is
  untested against a real hallucination.

## 8. What I would do next

1. **Extend the perturbation suite to prose.** Move facts between structured fields and text, rename
   document types, inject conflicting notes, and inject hallucinated quotes through a fake provider so
   the verification ablation measures something; report extractor recall per fact type.
2. **Confidence-based routing.** Score each check (unverified quotes, repair retries, disagreement
   between the two extractors or between med list and notes) and route low-confidence READYs to the
   nurse sample instead of sampling uniformly.
3. **Production monitoring of false READYs.** Log every packet, reconcile READY decisions against the
   nurse's disposition and day-of-surgery cancellations, alert on any false READY, and track the
   UNKNOWN rate per missing-datum key as an intake data-quality signal.
4. **Two-model agreement on safety facts.** Run the vitals and consent extractors with a second model
   or prompt and treat disagreement as UNKNOWN.
5. **Cheaper reading.** Skip templated documents (nutrition, PT, portal messages) with a small
   classifier and cover templated vitals lines with a regex pre-pass so the LLM handles only irregular prose.
