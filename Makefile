# Pre-op triage take-home. Every target below runs from a clean clone; the committed LLM cache
# means only `evals` (the provided remote scorer) and uncached inputs need OPENAI_API_KEY.

INPUT ?= data/patients_sample_50.jsonl
OUTPUT ?= data/baseline_outputs.jsonl
# Fresh `make evals` output if it exists, else the committed final report.
REPORT ?= $(if $(wildcard data/eval_report.json),data/eval_report.json,results/final_eval_report.json)
DETERMINISM_REPORT ?= data/determinism_report.json
MODEL ?= gpt-4.1-mini
CASE ?= case_00016
SUMMARY ?= results/final_summary.md

.PHONY: help test run baseline eval evals summary determinism score report baseline-naive profile assumptions lint format check all clean

help: ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

test: ## pytest (84 tests; no network, no API key)
	uv run --group dev python -m pytest tests -q

run: ## triage one case: make run CASE=case_00037
	uv run scripts/run_case.py --case-id $(CASE) --compact

baseline: ## pipeline over the 50 cases -> data/baseline_outputs.jsonl (cached: ~2 s, no key)
	uv run run_baseline.py --input $(INPUT) --output $(OUTPUT) --model $(MODEL)

summary: ## local scorer (harness metrics + confusion matrix + false READYs) -> results/final_summary.{md,json}
	uv run scripts/score_local.py --input $(INPUT) --outputs $(OUTPUT) --out-md $(SUMMARY) --out-json $(SUMMARY:.md=.json)

evals: ## provided remote scorer (OpenAI Evals API; needs OPENAI_API_KEY) -> data/eval_report.json
	uv run run_evals.py --input $(INPUT) --outputs $(OUTPUT) --report data/eval_report.json

eval: baseline summary ## baseline + summary (add `make evals` for the official report)

determinism: ## 10x replay of record 0 through triage_submission
	uv run run_evals.py --determinism --input $(INPUT) --model $(MODEL) --report $(DETERMINISM_REPORT)

score: ## print the primary score from $(REPORT)
	@python3 -c 'import json; r=json.load(open("$(REPORT)")); s=(r.get("primary_score",{}) or {}).get("value_pct"); print(s if s is not None else r.get("local_metrics_summary",{}).get("aggregate_local_score_pct", 0.0))'

report: ## interactive TUI over $(REPORT) (checks, evidence, assumptions)
	uv run --group dev view_report.py --report $(REPORT)

baseline-naive: ## the original single-call baseline (needs a key unless unchanged) -> results/baseline_*
	uv run run_baseline.py --implementation naive --input $(INPUT) --output results/baseline_outputs.jsonl --model $(MODEL)
	uv run run_evals.py --input $(INPUT) --outputs results/baseline_outputs.jsonl --report results/baseline_eval_report.json

profile: ## regenerate notes/data_profile.md
	uv run scripts/profile_data.py

assumptions: ## regenerate notes/assumptions.md from preop_triage/assumptions.py
	uv run scripts/export_assumptions.py

lint: ## ruff check + format check
	uv run --group dev ruff check .
	uv run --group dev ruff format --check .

format: ## ruff format + autofix
	uv run --group dev ruff check --fix .
	uv run --group dev ruff format .

check: lint test ## everything a reviewer can run without a key, fast
	$(MAKE) baseline summary determinism score

all: check

clean:
	rm -f data/baseline_outputs.jsonl data/eval_report.json data/determinism_report.json
