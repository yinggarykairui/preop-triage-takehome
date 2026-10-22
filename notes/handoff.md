# Handoff notes

> **Final-pass update (2026-10-22, second session).** The repo was taken through a submission pass:
> clean-clone reproduction, claims audit, write-up rewrite, lint/format (ruff, config in `pyproject.toml`),
> dependency pins, Makefile targets (`make help`), `notes/assumptions.md` + sync test, and
> `notes/submission_checklist.md` (what was verified, what changed, remaining risks, reviewer commands).
> Read the checklist first; the notes below describe the build session and remain accurate except
> where the checklist says otherwise (test count is now 90; `make perturb` / `make ablation` and `eval/` were added in a third session; `make score`/`make report` fall back to
> `results/final_eval_report.json`; A3/A7 wording was aligned with the code).

## Build session notes (written 2026-10-22, end of first build session)

For a fresh agent picking this repo up. Everything here was verified in-session; where something
is a judgement call it is labelled as one. Read this, then `WRITEUP.md`, then the code.

## 0. Environment facts you need before running anything

- Repo: cloned from `https://github.com/cadencerpm/preop-exercise` (link is a hyperlink inside the
  take-home PDF, not visible in extracted text). Our work is 8 commits on top of upstream `91fbf1d`.
  Remote `origin` still points at Cadence's repo: **do not push there.**
- Submission goes through the Greenhouse link in the 2026-10-19 email from Cadence recruiting,
  together with a `/export` of the Claude Code session. Deadline: one week from 2026-10-19.
- `uv` was installed with Homebrew (`uv 0.13.5`); Python 3.11.14. `uv run` resolves deps from
  `pyproject.toml` (`openai`, `pydantic`; dev group adds `pytest`, `textual`, `rich`). The three
  harness scripts carry inline script metadata and uv honours that when invoked directly.
- **API key:** `OPENAI_API_KEY` is not set in any shell rc. The key used for every live call came from
  the user's own `~/Desktop/VLM Augmented LLM/.env` (the keys in `docker-saige/.env` and
  `BRITE/universal-scraper/.env` return 401). It was copied only to the session scratchpad
  (`/private/tmp/claude-501/.../scratchpad/env.sh`), which will not survive. Re-export it from that
  `.env` if you need live calls. **With the committed cache you do not need a key** for
  `make baseline`, `make summary`, `make determinism`, `make test`, `scripts/run_case.py` on the
  50 sample cases. You need it only for new/changed prompts, new inputs, and `make evals` (the
  provided harness creates a remote OpenAI Evals run).

## 1. Architecture (what runs when `core.triage_submission(submission, model=...)` is called)

```
run_baseline.py ──► core.triage_submission ──► preop_triage.pipeline.triage
    1. extract_all()      preop_triage/extract.py   one DocFacts call per document (+ one AnticoagFacts
                                                     call per document whose text matches the anticoag
                                                     regex in normalize.mentions_anticoagulation);
                                                     ThreadPoolExecutor, LLM_MAX_WORKERS=6
    2. quote verification  preop_triage/verify.py    every positive claim must quote the doc; one repair
                                                     retry listing failed quotes; leftovers = unverified
    3. build_case_facts()  preop_triage/pipeline.py  raw JSON + extractions -> rules.CaseFacts
    4. run_all_checks()    preop_triage/rules.py     pure functions; Check(status PASS/FAIL/UNKNOWN/N/A)
    5. decide()/build_issues()                       precedence + MISSING_REQUIRED_DATA grouping
    6. assemble_packet()                             schemas.TriagePacket (decision, issues, checks, meta)
```

- `preop_triage/llm.py`: `CachedLLM` wraps a `Provider` (only `OpenAIProvider` exists; uses
  `client.responses.parse(text_format=<pydantic model>)`, temperature 0 unless model starts with
  `o`/`gpt-5`). Cache key = sha256 of {provider, model, instructions, user_text, schema_name,
  schema JSON, temperature}; files in `cache/llm/<sha>.json` (760 committed). **Changing a prompt
  string or a schema field invalidates the whole cache for that extractor** (~300 live calls, ~25 min
  wall clock sequential-per-case, pennies in cost).
- `preop_triage/schemas.py`: extractor outputs (`DocFacts`, `AnticoagFacts`) and the packet. All
  extractor fields are required (strict structured outputs); nullable via `| None`.
- `preop_triage/normalize.py`: `parse_date`/`parse_datetime` (UTC, day granularity),
  `celsius_to_fahrenheit`, `canonical_lab(code, display)` -> CBC/CMP/BMP/None, `canonical_anticoagulant`
  (brand->generic), `is_antiplatelet`, `Reading` + `most_recent_reading` (tie-break).
- `preop_triage/assumptions.py`: A1–A19 text; `Check.assumptions` cites IDs; `WRITEUP.md` §4 was
  generated from this dict (A4 was regenerated after an edit; if you change an assumption, re-sync §4).
- `baseline.py`: the original naive one-call implementation (`triage_submission_naive`), used by
  `make baseline-naive` and `tests/test_baseline_naive.py`.
- `view_report.py`: provided TUI, extended to render `summary`, evidence lists (doc_id + quote +
  UNVERIFIED flag), `decision_rationale`, `reference_dates`, `checks`, `assumptions_applied`, `meta`.
  Verified headlessly with Textual's `run_test` pilot (script lived in scratchpad; not committed).
- `scripts/`: `profile_data.py` (-> `notes/data_profile.md`), `run_case.py` (`--case-id/--index/--file`,
  `--compact`), `score_local.py` (harness metrics + confusion matrix + per-category P/R + miss list ->
  `results/final_summary.{md,json}`).
- Makefile: `make eval` = `baseline` (pipeline over 50 cases -> `data/baseline_outputs.jsonl`) +
  `evals` (remote harness -> `data/eval_report.json`) + `summary`. Note the target named `baseline`
  is the harness's name for "run triage_submission"; the naive baseline is `baseline-naive`.

## 2. Harness interface (do not break)

- `run_baseline.py` calls `triage_submission(submission=<dict>, model=<str>)` and writes
  `output.model_dump()`; `run_evals.py` scores only `output.decision` and
  `{issue.category for issue in output.issues}` (exact set equality) plus JSON validity. Labels are
  `label.decision`, `label.categories`, `label.rationale` in `data/patients_sample_50.jsonl`.
- `TriagePacket` keeps `decision`, `issues[].category`, `explanation` (= `decision_rationale`), and
  `issues[].description` (= summary) for the stock viewer.
- Category string is `ANTICOAGULATION_MANAGEMENT` (harness Literal + labels); the PDF's
  "ANTICOAGULATION_MANAGEMENTJSON" is an extraction artifact (A18).

## 3. Latest numbers (all reproducible from cache)

| artifact | value |
|---|---|
| `results/baseline_eval_report.json` (naive, harness) | 73.33% aggregate; decision 70%, categories 52%, schema 98%; 1 false READY (case_00026) |
| `results/run1_*` (pipeline, first full run) | 98.0%; misses case_00011, case_00037 (both extraction) |
| `results/final_eval_report.json` (pipeline, harness) | **100.0%** aggregate; decision/categories/schema 100% |
| `results/final_summary.md` (local) | confusion diagonal 17/25/8; per-category P/R 100%; 0 false READY |
| `results/determinism_report.json` | 100 / 100 / 100 (record 0, 10 runs, all from cache) |
| final run telemetry | 342 live calls, 0 provider failures, 2 unverified quotes (both correct rejections) |
| tests | `make test` -> 84 passed (no network) |

The 100% is in-sample: labels were visible while iterating and two prompts were revised after
seeing two misses. Treat it as "no known miss", not as a generalization estimate.

## 4. Assumptions and why (the non-obvious ones; full list in `preop_triage/assumptions.py`)

- **Missing BP or temperature -> UNKNOWN -> MISSING_REQUIRED_DATA (A9).** The policy's "required
  field missing -> NEEDS_FOLLOW_UP" clause is applied to vitals. Labels agree in 5 cases
  (case_00009/11/13/21/22). The alternative ("no reading = no exclusion") is the unsafe direction.
- **Vitals from free text count (A7),** incl. the H&P exam line and nursing addenda; "see flowsheet",
  "vitals deferred" and patient-reported home values do not. Labels explicitly use text vitals
  (case_00005, 00016, 00031, 00047).
- **Tie-break (A8):** same latest date with any time-less reading, or identical times -> most abnormal
  reading wins. Only matters near thresholds; chosen for safety. Not exercised by any label.
- **Procedure date (A4):** structured field, else a document date that is an explicit scheduled/target
  date, only if all stated dates agree, no verified "TBD" statement exists, and the date is not before
  the document stating it. Both null-date cases (00011, 00044) are TBD -> MISSING_REQUIRED_DATA only;
  window checks that depend on the date are folded into that one issue (labels do the same).
- **Risk (A5):** structured only, never inferred from procedure name. With risk unknown, a lab check
  still FAILs if it fails under every risk (no CBC at all) and PASSes only if it passes under every
  risk; otherwise UNKNOWN. Labels for 00029/00039 (risk null, labs fine) are MISSING_REQUIRED_DATA only.
- **H&P (A12):** any document whose *text* is an H&P counts, incl. annual-wellness/establish-care
  H&Ps; most recent one is checked; "H&P not on file" references are not H&Ps. The policy does not
  require a pre-op H&P, so `is_preop_evaluation` is reported but not enforced. In the sample every
  wellness H&P is out of window so this never bit; it could on other data.
- **Consent (A13):** needs a patient signature (physician attestation alone is not), for the planned
  procedure (LLM judges the match given `procedure_type`); any signed consent wins over pending ones
  (case_00007/00049 supersession); signed-for-other-procedure fails (case_00024).
- **Labs (A11):** canonicalized from code AND display; BMP never CMP; only final/corrected/amended
  count; entered-in-error skipped and the next most recent used (case_00004/06/41); results after the
  procedure date excluded (A3, never occurs in sample: procedure_date == submission date in all 48).
- **Anticoagulant status (A15):** med list active=true -> current; active=false -> not current unless
  the most recent note says current (then UNKNOWN); active=null -> most recent note decides, else
  UNKNOWN (case_00033 -> MISSING_REQUIRED_DATA); a note saying the patient currently takes a drug
  absent from the list makes it current (case_00000/27/38). Antiplatelets never count (A14).
- **Plan (A16):** the most recent plan document naming the current drug (brand/generic mapped) must
  have explicit pre-op AND post-op instructions and no deferral. A later incomplete note supersedes an
  earlier complete plan (judged ambiguous), and both are cited in evidence.
- **Review time (A6):** `metadata.submission_received_at`; vitals are never discarded for age.
- **Fail-safe (A17):** unverified facts and LLM failures can only lower a check to UNKNOWN; failed
  document extraction is its own UNKNOWN check -> NEEDS_FOLLOW_UP + MISSING_REQUIRED_DATA.

## 5. Bugs found and fixed (so you don't re-find them)

- Upstream `.gitignore` had `.env ` with a trailing space, so `.env` was not ignored. Fixed.
- Run 1 miss, case_00011: extractor returned the consent's signature date as `DATE_STATED` procedure
  date. Fixed by prompt definition + code guards (A4).
- Run 1 miss, case_00037: anticoag extractor flagged an H&P "continue home medications except as
  directed by perioperative instructions" line as a perioperative plan for Xarelto; it was newer than
  the real 03/27 plan and shadowed it. Fixed by prompt ("named anticoagulant, generic lines are not a
  plan") + evidence of superseded plans.
- Verifier: gpt-4.1-mini writes `°F` as `\x176F` (control char + "6") and sometimes drops parentheses.
  Verifier now removes a control char plus the character it garbled, removes degree signs, and has a
  punctuation-insensitive tier that keeps digits exact. Unverified quotes went 68 -> 11 -> 2.
- `vitals_deferred_or_not_recorded` was set with a paraphrased quote on every note lacking vitals
  (52 unverified quotes, no decision impact). Prompt/schema now require the quoted phrase.
- `CachedLLM.provider_name` instantiated `OpenAI()` (needs a key) even on cache-only runs; fixed.
- The legacy `tests/test_triage_submission.py` tested the naive call shape; moved to
  `tests/test_baseline_naive.py` against `baseline.py`.

## 6. Label disagreements

None found. Every label was consistent with the policy under the assumptions above. Places where a
different policy reading is defensible are listed in `notes/error_analysis.md` (last section).

## 7. Unfinished, fragile, or worth knowing

- **Cache invalidation is total per extractor.** Any edit to `DOC_FACTS_INSTRUCTIONS`,
  `ANTICOAG_INSTRUCTIONS`, `_doc_user_text`, or a `DocFacts`/`AnticoagFacts` field description changes
  every cache key. Budget a ~25-minute live rerun and regenerate the fixture cache afterwards:
  `rm -rf tests/fixtures/llm_cache && LLM_CACHE_DIR=tests/fixtures/llm_cache uv run scripts/run_case.py --case-id case_00016 --compact`
  (`tests/test_extraction_fixtures.py` fails loudly on a cache miss; it never calls the network).
- **Negative claims are unverifiable by design** (NOT_A_CONSENT, "no vitals in this note",
  `is_completed_hp=false`). A missed reading is only caught by another reading or a nurse.
- **Consent "matches planned procedure" is an LLM judgement** fed with `procedure_type`; code cannot
  verify it. Same for `is_preop_evaluation`, `explicit`, `deferred_to_another_team`.
- **Anticoag extractor prefilter** is a regex (`normalize.ANTICOAG_TEXT_HINT`): drug names, "anticoag*",
  "blood thinner*", "doac", "bridg*", "inr". A note that says "on a blood-thinning medicine" with a
  hyphen would be missed by the prefilter. Widen it if you see such phrasing.
- **`most_recent_reading` treats a document-only date (no time) as tied with same-day timed readings**
  (A8). A nursing note with vitals but no clock time on the same day as a later structured reading will
  make the more abnormal one win. Conservative, but could hold a patient on an older high reading.
- **Only one provider is implemented.** `make_provider` raises for anything but `openai`; adding
  Anthropic means implementing `Provider.complete` with the same strict-schema contract.
- **`run_evals.py` eval mode is remote** and sometimes slow; `make summary` is the local equivalent.
- **WRITEUP.md is ~2,800 words** (longer than the "1–2 pages" aim) because of the assumption list and
  tables. If the reviewer wants shorter, §4 can be replaced with a pointer to `assumptions.py`.
- **Not done:** confidence scoring / routing, larger eval set, Anthropic provider, a regex pre-pass
  for templated vitals lines, a CI workflow. `WRITEUP.md` §8 lists them in priority order.
- `results/*.log` are gitignored; everything else in `results/` is committed. `data/baseline_outputs.jsonl`,
  `data/eval_report.json`, `data/determinism_report.json` are gitignored (upstream choice) but copies
  live in `results/final_*` and `results/determinism_report.json`.

## 8. Quick verification sequence for a fresh checkout

```bash
uv --version && make test                    # 84 passed, no key needed
make baseline && make summary                # 100.0%, 0 live calls (cache hits only)
make determinism                             # 100/100/100
uv run scripts/run_case.py --case-id case_00037 --compact   # READY; plan for rivaroxaban PASS
export OPENAI_API_KEY=...; make evals        # only if you need the official report regenerated
```
