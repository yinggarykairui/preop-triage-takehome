# Pre-Op Scheduling Triage (Cadence take-home)

A triage agent that reads a patient's pre-op submission package and returns a
clearance decision (`READY | NEEDS_FOLLOW_UP | NOT_CLEARED`) plus an evidence
packet a pre-op nurse can verify in under a minute.

The design principle is **the LLM reads, the code decides**:

```
raw JSON ─► normalize (code) ─► extract facts (LLM, structured, per document)
         ─► verify quotes (code) ─► rule engine (pure, deterministic code)
         ─► decision + evidence packet (JSON)
```

Start with `WRITEUP.md` (approach, results, error analysis; 10 minutes). Supporting detail
lives in `notes/`: `assumptions.md`, `error_analysis.md`, `data_profile.md`, `submission_checklist.md`.

## Reviewer's path (no API key needed)

Requires Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/) (`brew install uv`). The first
`uv run` creates `.venv` and installs the pinned dependencies from `uv.lock`.

```bash
make test             # 90 tests, no network                              ~2 s (first run adds ~5 s of installs)
make baseline summary # pipeline over the 50 cases from the committed cache, then score it     ~2 s
make determinism      # 10x replay of record 0: 100 / 100 / 100           ~2 s
make run CASE=case_00037   # one case, compact evidence packet            <1 s
make perturb          # 170 constructed mutations -> results/perturbation.md  ~4 s
make ablation         # no-verify / no-fail-safe variants -> results/ablation.md  ~20 s
make report           # TUI over the final harness report (q to quit)
make lint             # ruff check + format check
```

`make help` lists every target. All of the above replay the committed LLM cache (`cache/llm/`),
so they are free and byte-for-byte reproducible. Only two things need `OPENAI_API_KEY`:
`make evals` (the provided scorer creates a remote OpenAI Evals run) and any input or prompt
the cache has not seen.

| run | cached | uncached (gpt-4.1-mini) | API cost, uncached |
|---|---|---|---|
| `make test` | ~2 s | n/a (never calls the network) | $0 |
| `make run CASE=…` | <1 s | 5–30 s | <$0.01 |
| `make baseline` (50 cases) | ~2 s | ~15–25 min, ~340 calls | ~$0.40 |
| `make determinism` | ~2 s | ~1–2 min | <$0.05 |
| `make perturb` (170 mutations) | ~4 s | ~2 min for the 22 text mutations (28 calls); the rest never call the API | ~$0.03 |
| `make ablation` (4 variants × 220 cases) | ~20 s | n/a (replays the same cache) | $0 |
| `make evals` | n/a | ~30–60 s (remote scoring only) | ~$0 (no model calls) |
| `make baseline-naive` | n/a (uncached) | ~3 min, 50 calls | ~$0.10 |

Cost figures are estimates from prompt and response sizes at list prices.

## Layout

| path | what |
|---|---|
| `core.py` | harness entry point `triage_submission(submission, model=...)` → `TriagePacket`; shared input schemas |
| `preop_triage/normalize.py` | dates (UTC, day granularity), °C→°F, lab canonicalization (`CBC`/`CMP`/`BMP`), drug brand→generic, most-recent-vital selection |
| `preop_triage/extract.py` | two per-document LLM extractors (document facts; anticoagulation facts) with verbatim-quote verification and one repair retry |
| `preop_triage/verify.py` | quote verifier (exact, normalized, or punctuation-insensitive substring; digits always exact) |
| `preop_triage/rules.py` | the rule engine: one pure function per rule, `decide()`, `build_issues()` |
| `preop_triage/pipeline.py` | orchestration and evidence-packet assembly |
| `preop_triage/llm.py` | provider abstraction, strict structured outputs at temperature 0, disk cache, fail-safe errors |
| `preop_triage/assumptions.py` | the numbered assumptions (A1–A19) and the functions that enforce each |
| `baseline.py` | the original naive single-call baseline, kept for comparison |
| `run_baseline.py`, `run_evals.py`, `view_report.py` | the provided harness (interface unchanged; viewer extended to show checks and evidence) |
| `scripts/` | `run_case.py`, `score_local.py`, `profile_data.py`, `export_assumptions.py` |
| `eval/` | `perturb.py` (seeded perturbation suite) and `ablation.py` (verification / fail-safe switched off) |
| `preop_triage/config.py` | `TRIAGE_ABLATE` switches used only by the ablation |
| `tests/` | pytest suite (rule engine, normalization, verifier, extraction fixtures, assumption sync) |
| `cache/llm/` | committed LLM response cache (788 files, 3 MB) so reruns are free and reproducible |
| `results/` | baseline, run-1 and final harness reports, outputs and local summaries; `perturbation.*`, `ablation.*` |
| `notes/` | assumptions, error analysis, data profile, handoff, submission checklist |

## Setup

```bash
export OPENAI_API_KEY="sk-..."     # only for uncached LLM calls and for make evals
```

| variable | default | purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI credential (extraction + the harness's Evals API call) |
| `MODEL` (make) / `--model` | `gpt-4.1-mini` | extraction model; any OpenAI model id |
| `LLM_PROVIDER` | `openai` | provider selector (`preop_triage/llm.py` `make_provider`) |
| `LLM_CACHE_DIR` | `cache/llm` | where cached structured responses live |
| `LLM_DISABLE_CACHE` | unset | set to `1` to force live calls |
| `LLM_TIMEOUT_S` | `60` | per-call timeout; a timeout degrades the document to UNKNOWN |
| `LLM_MAX_WORKERS` | `6` | parallel document extractions per case |
| `TRIAGE_ABLATE` | unset | ablation only: `no_verify`, `no_failsafe` (comma-separated) |

## Run a single case

```bash
uv run scripts/run_case.py --case-id case_00016 --compact   # decision, issues, check statuses
uv run scripts/run_case.py --index 5                        # full evidence packet (JSON)
uv run scripts/run_case.py --file my_submission.json        # a bare submission package (needs a key)
```

From Python:

```python
from core import triage_submission

packet = triage_submission(submission_dict, model="gpt-4.1-mini")
packet.decision, packet.issues, packet.checks, packet.reference_dates
```

## Run the full harness

```bash
make baseline    # pipeline over the 50 cases -> data/baseline_outputs.jsonl
make summary     # scripts/score_local.py -> results/final_summary.{md,json}; same metrics as the harness, plus confusion matrix
make evals       # run_evals.py -> data/eval_report.json (needs OPENAI_API_KEY; creates a remote eval run)
make score       # print the primary score (uses data/eval_report.json if present, else results/final_eval_report.json)
make report      # TUI over the same report
make determinism # 10x replay of record 0 through triage_submission
make baseline-naive  # the original single-call baseline -> results/baseline_*.json(l) (needs a key)
make perturb     # eval/perturb.py: seeded mutations with answers known by construction -> results/perturbation.{md,json}
make ablation    # eval/ablation.py: TRIAGE_ABLATE variants on the sample + perturbation sets -> results/ablation.{md,json}
```

## Tests

```bash
make test
```

| file | n | covers |
|---|---|---|
| `tests/test_rules.py` | 50 | rule-engine boundaries (179/180, 109/110, 100.4/100.5, day 30/31 and 14/15), most-recent selection, entered-in-error labs, missing date/risk, plan completeness, decision precedence |
| `tests/test_normalize_verify.py` | 25 | lab/drug canonicalization, unit conversion, date parsing, quote verifier (incl. mojibake and dropped punctuation) |
| `tests/test_extraction_fixtures.py` | 3 | extraction layer end to end against a committed fixture cache; a dead provider yields NEEDS_FOLLOW_UP, never READY |
| `tests/test_assumptions.py` | 3 | every assumption names code that exists; `notes/assumptions.md` is current |
| `tests/test_perturb_ablation.py` | 6 | ablation switches; perturbation generator is seeded, well-formed, and structured mutations never touch documents |
| `tests/test_baseline_naive.py` | 3 | the naive baseline's call shape (mocked client) |

None of the tests call the network. The fixture test fails loudly on a cache miss instead of
calling the API; regenerate with
`LLM_CACHE_DIR=tests/fixtures/llm_cache uv run scripts/run_case.py --case-id case_00016 --compact`.

## Output contract

The harness scores `decision` and the set of `issues[].category`, and checks that the JSON
parses. `explanation` and `issues[].description` are kept so the stock viewer works; everything
else is for the nurse reviewer:

```json
{
  "case_id": "...", "patient_id": "...",
  "decision": "NEEDS_FOLLOW_UP",
  "decision_rationale": "Not ready because of: RULE_3 Plan for apixaban.",
  "explanation": "(same as decision_rationale)",
  "reference_dates": {"procedure_date": "2026-03-01", "procedure_date_source": {"source": "procedure.procedure_date"}, "review_time": "...", "procedure_risk": "LOW"},
  "issues": [{"category": "ANTICOAGULATION_MANAGEMENT", "rule": "RULE_3", "summary": "...", "resolution": "...",
              "evidence": [{"source": "medications[1]", "value": "apixaban (active=True)"},
                           {"source": "document", "doc_id": "...", "doc_type": "...", "date": "...", "quote": "Hold Xarelto for the 2 days before surgery", "verified": true}]}],
  "checks": [{"rule": "RULE_2", "name": "CBC within window", "status": "PASS", "category": "REQUIRED_TESTING", "summary": "...",
              "inputs": {"result_date": "2026-02-11", "days_before_procedure": 18, "window_days": {"LOW": 30}}, "evidence": [...], "assumptions": ["A1", "A2", "A3", "A5", "A11"]}],
  "assumptions_applied": ["A1", "A2", "..."],
  "meta": {"model": "gpt-4.1-mini", "provider": "openai", "pipeline_version": "1.0.0", "llm_calls": 0, "llm_cache_hits": 7, "llm_failures": 0, "unverified_quotes": 0, "unverified_quote_details": [], "documents_extracted": 5, "documents_failed": []}
}
```

The schema is `preop_triage/schemas.py::TriagePacket`; all 50 committed outputs validate against it.
Every issue carries at least one evidence pointer to a structured field path or a `doc_id` plus a
verbatim quote that was verified against the document text.
