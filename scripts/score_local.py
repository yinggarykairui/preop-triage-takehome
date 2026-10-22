#!/usr/bin/env python3
"""Score triage outputs locally against the labels in the input JSONL.

Reproduces the harness metrics (json_schema_valid, decision_match_oracle,
issue_categories_match_oracle, aggregate) without the OpenAI Evals API, and adds a
3x3 confusion matrix, per-category issue precision/recall, and the false-READY list.
Writes a Markdown summary and a JSON file with per-case rows for error analysis.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

DECISIONS = ["READY", "NEEDS_FOLLOW_UP", "NOT_CLEARED"]
CATEGORIES = ["REQUIRED_DOCUMENTATION", "REQUIRED_TESTING", "ANTICOAGULATION_MANAGEMENT",
              "ACUTE_SAFETY_EXCLUSION", "MISSING_REQUIRED_DATA"]


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="data/patients_sample_50.jsonl")
    ap.add_argument("--outputs", default="data/baseline_outputs.jsonl")
    ap.add_argument("--out-md", default="results/final_summary.md")
    ap.add_argument("--out-json", default="results/final_summary.json")
    ap.add_argument("--title", default="Pipeline")
    args = ap.parse_args()

    cases = load_jsonl(Path(args.input))
    outputs = {int(r.get("record_index", i)): r for i, r in enumerate(load_jsonl(Path(args.outputs)))}

    rows, confusion = [], Counter()
    cat_tp, cat_fp, cat_fn = Counter(), Counter(), Counter()
    for idx, case in enumerate(cases):
        label = case["label"]
        row = outputs.get(idx, {})
        out = row.get("output") if isinstance(row.get("output"), dict) else None
        valid = bool(out) and out.get("decision") in DECISIONS and isinstance(out.get("issues"), list)
        actual = out["decision"] if valid else "INVALID"
        expected_cats = sorted(set(label["categories"]))
        actual_cats = sorted({i.get("category") for i in out["issues"]}) if valid else []
        m = {"json_schema_valid": valid, "decision_match_oracle": valid and actual == label["decision"],
             "issue_categories_match_oracle": expected_cats == actual_cats}
        confusion[(label["decision"], actual)] += 1
        for c in CATEGORIES:
            e, a = c in expected_cats, c in actual_cats
            cat_tp[c] += e and a
            cat_fp[c] += (not e) and a
            cat_fn[c] += e and (not a)
        rows.append({
            "record_index": idx, "case_id": case["case_id"], "expected_decision": label["decision"], "actual_decision": actual,
            "expected_categories": expected_cats, "actual_categories": actual_cats, "metrics": m,
            "aggregate_local_score": 100.0 * sum(m.values()) / 3, "label_rationale": label.get("rationale"),
            "actual_rationale": (out or {}).get("decision_rationale") or (out or {}).get("explanation"),
            "error": row.get("error"),
            "meta": (out or {}).get("meta"),
        })

    n = len(rows)
    summary = {k: round(100.0 * sum(r["metrics"][k] for r in rows) / n, 2) for k in rows[0]["metrics"]}
    summary["aggregate_local_score_pct"] = round(sum(r["aggregate_local_score"] for r in rows) / n, 2)
    false_ready = [r["case_id"] for r in rows if r["actual_decision"] == "READY" and r["expected_decision"] != "READY"]
    misses = [r for r in rows if not all(r["metrics"].values())]

    L = [f"# {args.title}: local score on `{Path(args.input).name}`", "",
         f"Records: {n}", "", "| metric | value |", "|---|---|"]
    L += [f"| {k} | {v}% |" for k, v in summary.items()]
    L += ["", "## Decision confusion matrix (rows = label, columns = predicted)", "",
          "| label \\ predicted | " + " | ".join(DECISIONS + ["INVALID"]) + " |", "|---|" + "---|" * 4]
    for e in DECISIONS:
        L.append(f"| {e} | " + " | ".join(str(confusion[(e, a)]) for a in DECISIONS + ["INVALID"]) + " |")
    L += ["", f"**False READYs (label not READY, predicted READY): {len(false_ready)}** " + (", ".join(false_ready) if false_ready else ""), ""]
    L += ["## Per-category issue precision / recall", "", "| category | TP | FP | FN | precision | recall |", "|---|---|---|---|---|---|"]
    for c in CATEGORIES:
        tp, fp, fn = cat_tp[c], cat_fp[c], cat_fn[c]
        prec = f"{100 * tp / (tp + fp):.0f}%" if tp + fp else "n/a"
        rec = f"{100 * tp / (tp + fn):.0f}%" if tp + fn else "n/a"
        L.append(f"| {c} | {tp} | {fp} | {fn} | {prec} | {rec} |")
    L += ["", f"## Misses ({len(misses)})", ""]
    for r in misses:
        L += [f"### {r['case_id']} (record {r['record_index']})",
              f"- expected: {r['expected_decision']} {r['expected_categories']}",
              f"- actual:   {r['actual_decision']} {r['actual_categories']}",
              f"- label rationale: {r['label_rationale']}",
              f"- pipeline rationale: {r['actual_rationale']}", ""]
    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text("\n".join(L) + "\n")
    Path(args.out_json).write_text(json.dumps({"summary": summary, "confusion": {f"{e}->{a}": v for (e, a), v in confusion.items()},
                                               "false_ready": false_ready, "rows": rows}, indent=1))
    print("\n".join(L[:8 + len(summary)]))
    print(f"false READY: {false_ready}")
    print(f"wrote {args.out_md} and {args.out_json}")


if __name__ == "__main__":
    main()
