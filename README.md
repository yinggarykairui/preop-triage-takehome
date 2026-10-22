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

See `WRITEUP.md` for the architecture, assumptions, results and error analysis.
`notes/data_profile.md` and `notes/error_analysis.md` hold the supporting detail.

## Layout

| path | what |
|---|---|
| `core.py` | harness entry point `triage_submission(submission, model=...)` → `TriagePacket`; shared input schemas |
| `preop_triage/normalize.py` | dates (UTC, day granularity), °C→°F, lab canonicalization (`CBC`/`CMP`/`BMP`), drug brand→generic, most-recent-vital selection |
| `preop_triage/extract.py` | two per-document LLM extractors (document facts; anticoagulation facts) with verbatim-quote verification |
| `preop_triage/verify.py` | quote verifier (exact or whitespace/unicode-normalized substring) |
| `preop_triage/rules.py` | the rule engine: one pure function per rule, `decide()`, `build_issues()` |
| `preop_triage/pipeline.py` | orchestration and evidence-packet assembly |
| `preop_triage/llm.py` | provider abstraction, strict structured outputs at temperature 0, disk cache, fail-safe errors |
| `preop_triage/assumptions.py` | the numbered assumption list (A1–A19) cited by checks and packets |
| `baseline.py` | the original naive single-call baseline, kept for comparison |
| `run_baseline.py`, `run_evals.py`, `view_report.py` | the provided harness (unchanged interface) |
| `scripts/` | `profile_data.py`, `run_case.py`, `score_local.py` |
| `tests/` | pytest suite (rule engine, normalization, verifier, extraction fixtures) |
| `cache/llm/` | committed LLM response cache so reruns are free and reproducible |
| `results/` | baseline and final harness reports and summaries |

## Setup

Requires Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/) (`brew install uv`).
`uv run` creates `.venv` and installs `openai` + `pydantic` on first use.

```bash
export OPENAI_API_KEY="sk-..."     # only needed for uncached LLM calls and for run_evals.py
```

### Environment variables

| variable | default | purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | OpenAI credential (extraction + the harness's Evals API call) |
| `MODEL` (make) / `--model` | `gpt-4.1-mini` | extraction model; any OpenAI model id |
| `LLM_PROVIDER` | `openai` | provider selector (`preop_triage/llm.py` `make_provider`) |
| `LLM_CACHE_DIR` | `cache/llm` | where cached structured responses live |
| `LLM_DISABLE_CACHE` | unset | set to `1` to force live calls |
| `LLM_TIMEOUT_S` | `60` | per-call timeout; a timeout degrades the document to UNKNOWN |
| `LLM_MAX_WORKERS` | `6` | parallel document extractions per case |

## Run a single case

```bash
uv run scripts/run_case.py --case-id case_00016 --compact   # decision, issues, check statuses
uv run scripts/run_case.py --index 5                        # full evidence packet (JSON)
uv run scripts/run_case.py --file my_submission.json        # a bare submission package
```

From Python:

```python
from core import triage_submission
packet = triage_submission(submission_dict, model="gpt-4.1-mini")
packet.decision, packet.issues, packet.checks, packet.reference_dates
```

## Run the full harness

```bash
make eval        # = make baseline (pipeline over the 50 cases) + make evals (official scorer) + make summary
make report      # interactive TUI over data/eval_report.json (shows checks, evidence, assumptions)
make score       # print the primary score
make determinism # 10x replay of record 0 through triage_submission (cached → identical)
```

Individual pieces:

```bash
make baseline                         # writes data/baseline_outputs.jsonl using core.triage_submission
make evals                            # run_evals.py → data/eval_report.json (needs OPENAI_API_KEY; uses the Evals API)
make summary                          # scripts/score_local.py → results/final_summary.md (+ .json), no API needed
make baseline-naive                   # the original single-call baseline → results/baseline_*.json(l)
make profile                          # regenerate notes/data_profile.md
```

With the committed cache, `make baseline` and `make summary` run without any API
calls. `make evals` still needs a key because the provided harness creates a remote
eval run; `make summary` reproduces the same metrics locally.

## Tests

```bash
make test        # uv run --group dev python -m pytest tests -q
```

- `tests/test_rules.py` – rule-engine boundaries (179/180, 109/110, 100.4/100.5, day 30/31 and 14/15),
  most-recent selection, entered-in-error labs, missing date/risk, anticoagulation plan completeness,
  decision precedence. No LLM, no network.
- `tests/test_normalize_verify.py` – lab/drug canonicalization, unit conversion, date parsing, quote verifier.
- `tests/test_extraction_fixtures.py` – the extraction layer end to end against cached responses
  (fails loudly if the fixture is missing instead of calling the API).

## Output contract

`decision`, `issues[].category` and `explanation` are what the harness scores; everything
else is for the nurse reviewer:

```json
{
  "case_id": "...", "patient_id": "...",
  "decision": "NEEDS_FOLLOW_UP",
  "decision_rationale": "Not ready because of: RULE_3 Plan for apixaban.",
  "reference_dates": {"procedure_date": "2026-03-01", "procedure_date_source": {"source": "procedure.procedure_date"}, "review_time": "...", "procedure_risk": "LOW"},
  "issues": [{"category": "ANTICOAGULATION_MANAGEMENT", "rule": "RULE_3", "summary": "...", "evidence": [{"source": "medications[1]", "value": "apixaban (active=True)"}, {"source": "document", "doc_id": "...", "doc_type": "...", "date": "...", "quote": "Hold Xarelto for the 2 days before surgery", "verified": true}], "resolution": "..."}],
  "checks": [{"rule": "RULE_2", "name": "CBC within window", "status": "PASS", "inputs": {"result_date": "2026-02-11", "days_before_procedure": 18, "window_days": {"LOW": 30}}, "evidence": [...]}],
  "assumptions_applied": ["A1", "A2", "..."],
  "meta": {"model": "gpt-4.1-mini", "pipeline_version": "1.0.0", "llm_failures": 0, "unverified_quotes": 0}
}
```

Every issue carries at least one evidence pointer to a structured field path or a
`doc_id` plus a verbatim quote that was verified against the document text.
