# Submission checklist (final passes, 2026-10-22)

Two passes: the submission-readiness pass (§1–§5) and the depth pass that added the perturbation
suite and the ablation (§0). Everything was executed on a clean copy of the repository with
`OPENAI_API_KEY` unset, unless stated otherwise.

## 0. Depth pass: perturbation suite and ablation

A search for earlier ablation/perturbation work found nothing: no local or remote branch, stash,
worktree, reflog entry or dangling object contains it; nothing on disk under `eval/`, `results/`,
`review/` or nearby directories; the earlier session transcript never mentions it. It was built fresh.

- **`eval/perturb.py` (`make perturb`)**: 16 families, 170 seeded mutations, expected answers by
  construction. 148 structured mutations run from the committed cache; 22 text mutations
  (`plan_no_postop`, `consent_pending`, `temp_threshold_c_text`) were run once live (28 calls,
  ~90 s, ~$0.03) and their responses committed to `cache/llm/`, so `make perturb` needs no key.
  **Result: 170/170 pass, 0 false READYs** (`results/perturbation.md`, `.json`).
- **`eval/ablation.py` (`make ablation`)**: `TRIAGE_ABLATE=no_verify|no_failsafe`
  (`preop_triage/config.py`; wired into `extract.DocExtraction.verified`, `extract._failed_quotes`,
  `rules.decide`, `rules.build_issues`; production defaults unchanged, cached replay byte-identical).
  Sample 50 + 170 perturbations × 4 variants, ~20 s from cache. **Result** (`results/ablation.md`):
  full 100.0% / 0 false READYs on both sets; no-verify identical; no-fail-safe 90.7% with 5 false
  READYs on the sample and 96.5% with 6 on the perturbations.
- **Bug fixed (general, no record special-casing):** `core.TemperatureVital` lacked `value_c`, so a
  structured Celsius temperature was dropped by input validation before the pipeline saw it. Recorded
  in `results/perturbation.md`. No other bugs surfaced; every family passed on first run.
- **Tests:** +6 in `tests/test_perturb_ablation.py` (90 total). `make test`, `make baseline`,
  `make lint`, `make determinism` stayed green throughout; `results/final_outputs.jsonl` was
  refreshed because the echoed submission now carries `value_c: null` (packets unchanged).
- **Docs:** WRITEUP §4.1–4.2 (results, every number from `results/perturbation.md` and
  `results/ablation.md`), §7/§8 reworded; README reviewer's path, runtime/cost table, layout and test
  tables; `make check` now includes `perturb` and `ablation`.
- **Clean-copy re-run with no key** (this pass): `make test` 90 passed; `make baseline` 50/50 from
  cache; `make lint` clean; `make determinism` 100/100/100; `make perturb` 170/170; `make ablation`
  table reproduced; both Markdown reports came out identical to the committed ones (wall clock: perturb 3.8 s, ablation 19 s).

## 1. What was verified

**Clean-clone reproducibility** (fresh clone/copy in a temp directory, `uv 0.13.5`, Python 3.11.14)

| command | result | wall clock (cached) | uncached estimate | API cost (uncached) |
|---|---|---|---|---|
| `make test` | 90 passed, no network | ~2 s (+~5 s first-run installs) | n/a | $0 |
| `make baseline` | 50/50 packets, 0 live calls, 326 cache hits | ~2 s | ~15–25 min, ~340 calls | ~$0.40 |
| `make summary` | 100 / 100 / 100 / 100.0, 0 false READYs | <1 s | n/a | $0 |
| `make determinism` | 100 / 100 / 100 (10 runs, record 0) | ~2 s | ~1–2 min | <$0.05 |
| `make score` | 100.0 (falls back to `results/final_eval_report.json`) | <1 s | n/a | $0 |
| `make run CASE=case_00037` | READY, plan for rivaroxaban PASS | <1 s | 5–30 s | <$0.01 |
| `make lint` | ruff check + format: clean | ~1 s | n/a | $0 |
| `make perturb` | 170/170 mutations pass | ~4 s | ~2 min (22 text mutations) | ~$0.03 |
| `make ablation` | 4 variants × 220 cases | ~20 s | n/a | $0 |
| `make check` (all of the above) | passes end to end | ~35 s | | |
| `make report` | TUI driven headlessly with Textual's pilot: header, 50 rows, checks, evidence with doc_id, assumptions, meta all render | | | |
| `make evals` | **not re-run** (needs a key; creates a remote Evals run). The committed `results/final_eval_report.json` (100.0, run status `completed`) and `results/baseline_eval_report.json` (73.33) were inspected and their remote criteria match the local scorer | | ~30–60 s | ~$0 |
| fail-safe path | `LLM_DISABLE_CACHE=1`, no key, one case → NEEDS_FOLLOW_UP with MISSING_REQUIRED_DATA (never READY) | | | |

- The cached replay reproduces all 50 committed packets in `results/final_outputs.jsonl` byte for byte
  (ignoring the `llm_calls` / `llm_cache_hits` counters).
- `notes/data_profile.md` regenerates identically from `make profile`.

**Review page:** there is no standalone HTML review page; the provided TUI (`make report`) is the
review surface and was verified. The perturbation suite and ablation were added in the depth pass (§0).

**Claims audit** (every number in `WRITEUP.md` traced to an artifact)

| claim | source | status |
|---|---|---|
| baseline 73.33 / 70 / 52 / 98, 1 false READY (case_00026) | `results/baseline_eval_report.json`, `results/baseline_summary.md` | matches |
| run 1 98.0 / 98 / 96, misses case_00011 and case_00037 | `results/run1_eval_report.json`, `results/run1_summary.md` | matches |
| final 100 / 100 / 100, confusion diagonal 17/25/8, per-category 12/7/7/8/9 | `results/final_eval_report.json`, `results/final_summary.md`, regenerated by `make baseline summary` | matches |
| determinism 100/100/100 | `results/determinism_report.json`, regenerated by `make determinism` | matches |
| final run: 342 live calls, 0 failures | first-session telemetry; not reproducible from committed artifacts (the cached replay shows 326 hits because the hardened verifier triggers fewer repair calls) | restated as such in §4 |
| 2 unverified quotes (case_00005, case_00043) | `results/final_outputs.jsonl` meta | matches |
| run-1 68 unverified quotes | `results/run1_outputs.jsonl` meta | matches |
| 48/50 BP in text, 10 °C temps, 28 "see flowsheet", 39 doc types, 3–8 docs, ≤2,200 chars | recomputed from `data/patients_sample_50.jsonl` | matches |
| test counts (50 / 25 / 3 / 3 / 3 = 84) | `pytest --collect-only` | matches (write-up previously said "74 engine tests"; corrected) |
| ~6.5 calls per case, ~$0.40 per cold run | 321 base calls (284 doc + 37 anticoag) + repairs; ~780k input and ~200 output tokens per call at gpt-4.1-mini list prices | estimate, labelled as such |

- **Assumptions vs. code:** every A1–A19 text was diffed against `preop_triage/assumptions.py`
  (identical) and read against the implementing function. Two wordings had drifted and were aligned
  with the code: A3 (an H&P dated after the procedure date *fails* rather than being excluded) and A7
  (a text reading uses the stated measurement date, else the document date). No behaviour changed.
  `IMPLEMENTED_IN` now maps each ID to its functions; `tests/test_assumptions.py` fails if a named
  function disappears or `notes/assumptions.md` is stale.
- **Output schema:** all 50 committed outputs validate against `TriagePacket`; every issue carries at
  least one evidence pointer; the README example was corrected (the harness scores `decision` and
  the category set, not `explanation`) and extended with the real `meta` and `checks` fields.

**Secrets scan.** `git log --all -p` and every blob in `git rev-list --all --objects` were grepped
for `sk-…`, `sk-proj-…`, AWS, GitHub and Slack token shapes and `OPENAI_API_KEY=`. The only hit is the
placeholder `sk-...` in the README. No `.env` was ever tracked. **Nothing to rewrite.**

**Patient data.** The 45 synthetic patient names and `MRN-30000xx` identifiers in the sample appear
only in `data/`, in the committed LLM cache (quotes from the documents) and in `results/` (the
submissions are embedded in every harness report by the provided scorer). No real-looking data
exists elsewhere; nothing in code, notes or tests names a patient.

## 2. What changed in this pass

- **Dependencies pinned** to the versions in `uv.lock` (`openai==3.37.0`, `pydantic==2.14.1`,
  `pytest==9.1.1`, `textual==8.2.8`, `rich==15.0.0`, `ruff==0.17.2`), in `pyproject.toml` and in the
  three scripts' inline metadata.
- **Lint/format:** `[tool.ruff]` added (line length 120, `E F I UP B SIM`); `ruff format` applied to
  all 35 Python files; the remaining findings fixed by hand (ambiguous `l` names, import order, an
  unbound loop variable in a closure, `raise … from exc`). Prompts and schemas are untouched: the
  cached replay is still byte-identical.
- **Dead code removed:** the duplicate naive-baseline prompt and `build_user_prompt` in `core.py`
  (they live in `baseline.py`), the unused `pipeline.assumption_text`, a redundant antiplatelet
  clause in `_drugs`.
- **Docstrings and type hints:** every rule function and every public pipeline entry point has a
  docstring; the pipeline helpers have return annotations.
- **Assumptions:** `IMPLEMENTED_IN` map, `scripts/export_assumptions.py` → `notes/assumptions.md`
  (`make assumptions`), `tests/test_assumptions.py` (3 tests). A3/A7 wording aligned with the code.
- **Makefile:** `make help`, `run`, `lint`, `format`, `check`, `assumptions`; `score` and `report`
  fall back to `results/final_eval_report.json` when no fresh `data/eval_report.json` exists (they
  used to fail on a clean clone); `eval` no longer requires a key (`evals` is separate).
- **`.gitignore`:** `.env.*`, `*.env`, `*.log`, `.claude/` added.
- **README:** reviewer's path with runtime/cost table, Makefile targets, test table, corrected output
  contract.
- **WRITEUP:** rewritten to the requested shape (5-line TL;DR, architecture, assumptions table with
  code pointers, results incl. run 1, error analysis, depth and validation, limitations, next steps);
  the full assumption text moved to `notes/assumptions.md`; the missing ablation/perturbation study is
  stated as a limitation; the 342-vs-326 call count is explained.
- **Housekeeping:** the pasted session prompt file at the repo root was moved out of the repo;
  `notes/handoff.md` carries a pointer to this checklist and corrected counts.

The submission-readiness pass was committed as `d71f767`; the depth pass is the following commit.

## 3. Remaining risks and known issues

- **In-sample 100%.** Labels were visible during iteration and two prompts were revised after two
  misses. Stated plainly in the TL;DR, §4 and §7 of the write-up.
- **Perturbations are mostly structural.** 148/170 mutations change structured fields; prose-level
  robustness (renamed document types, conflicting notes, facts moved into text) is still unmeasured, and
  the verification ablation shows no effect because this data contains no decision-relevant
  hallucination to catch.
- **Cache invalidation is total per extractor.** Any edit to a prompt string or an extractor schema
  field changes every cache key; a live rerun (~20 min, ~$0.40) and a fixture regeneration are then
  needed, and `tests/test_extraction_fixtures.py` will fail loudly until the fixtures are refreshed.
- **`make evals` was not re-run** in this pass (no key in this session). The committed reports are
  from the first session and are consistent with the local scorer.
- **Live-run figures** (342 calls, ~25 min) come from the first session's telemetry; the committed
  artifacts only show the cached replay. The write-up labels them accordingly.
- **Single provider (OpenAI).** `LLM_PROVIDER` other than `openai` raises.
- **Results files embed the sample submissions** (the provided scorer does this). Harmless for
  synthetic data, but worth knowing before pointing the harness at anything real.
- `origin` still points at Cadence's upstream repository. **Do not push there.** Submit via the
  Greenhouse link.

## 4. Exact command sequence for a reviewer

```bash
git clone <your-repo-url> preop-triage && cd preop-triage
brew install uv                      # if needed; Python >= 3.11

make test                            # 84 passed, no network, no key
make baseline summary                # 50 cases from the committed cache -> 100.0%, 0 false READYs
make determinism                     # 100 / 100 / 100
make score                           # 100.0 (results/final_eval_report.json)
make run CASE=case_00037             # one case: READY, plan for rivaroxaban PASS
make report                          # TUI over the final report; arrow keys, q to quit
make lint                            # ruff clean
make perturb                         # 170/170 constructed mutations pass
make ablation                        # fail-safe off -> 5 + 6 false READYs; full pipeline 0

# Optional, needs a key: regenerate the official report with the provided remote scorer
export OPENAI_API_KEY=sk-...
make evals && make score
```

To commit this pass (from the repo root, on `main`):

```bash
git status   # the final-pass and depth-pass commits are already on main; commit only what you add (session exports)
```

## 5. Files to add by hand

The take-home asks for the Claude Code session export alongside the repository. None are in the
repo yet. Suggested location: `notes/sessions/`.

1. **Session 1** (build session, 2026-10-22): `/export` from the session that produced commits
   `00b4bf1` … `e060545` (phase 0 through the handoff notes).
2. **Session 2** (submission-readiness pass, 2026-10-22, commit `d71f767`).
3. **Session 3** (depth pass: perturbation suite + ablation, 2026-10-22, this session): `/export`
   after it ends.
4. Any earlier exploratory session that read the take-home PDF or profiled the data before
   `00b4bf1`, if one existed.

After adding them, run `make check` once more and commit.
