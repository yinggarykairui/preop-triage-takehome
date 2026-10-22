INPUT ?= data/patients_sample_50.jsonl
OUTPUT ?= data/baseline_outputs.jsonl
REPORT ?= data/eval_report.json
DETERMINISM_REPORT ?= data/determinism_report.json
MODEL ?= gpt-4.1-mini

SUMMARY ?= results/final_summary.md

.PHONY: baseline baseline-naive evals determinism score report test all clean eval summary profile

baseline:
	uv run run_baseline.py \
		--input $(INPUT) \
		--output $(OUTPUT) \
		--model $(MODEL)

# The original single-call baseline, for comparison (writes to results/).
baseline-naive:
	uv run run_baseline.py \
		--implementation naive \
		--input $(INPUT) \
		--output results/baseline_outputs.jsonl \
		--model $(MODEL)
	uv run run_evals.py \
		--input $(INPUT) \
		--outputs results/baseline_outputs.jsonl \
		--report results/baseline_eval_report.json

# Local scoring (no OpenAI Evals API): same metrics as run_evals.py plus a confusion
# matrix, per-category precision/recall and the list of false READYs.
summary:
	uv run scripts/score_local.py \
		--input $(INPUT) \
		--outputs $(OUTPUT) \
		--out-md $(SUMMARY) \
		--out-json $(SUMMARY:.md=.json)

# One command: run the pipeline over the sample, score it with the harness, summarize.
eval: baseline evals summary

profile:
	python3 scripts/profile_data.py

evals:
	uv run run_evals.py \
		--input $(INPUT) \
		--outputs $(OUTPUT) \
		--report $(REPORT)

determinism:
	uv run run_evals.py \
		--determinism \
		--input $(INPUT) \
		--model $(MODEL) \
		--report $(DETERMINISM_REPORT)

score:
	@python3 -c 'import json; r=json.load(open("$(REPORT)")); s=(r.get("primary_score",{}) or {}).get("value_pct"); print(s if s is not None else r.get("local_metrics_summary",{}).get("aggregate_local_score_pct", 0.0))'

report:
	uv run view_report.py --report $(REPORT)

test:
	uv run --group dev python -m pytest tests -q

all: baseline evals determinism score

clean:
	rm -f data/baseline_outputs.jsonl \
		data/eval_report.json \
		data/determinism_report.json
