#!/usr/bin/env python3
"""Triage a single case and print the evidence packet.

Examples:
  uv run scripts/run_case.py --case-id case_00016
  uv run scripts/run_case.py --index 3 --model gpt-4.1-mini
  uv run scripts/run_case.py --file my_submission.json      # a bare submission package
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import triage_submission  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(ROOT / "data" / "patients_sample_50.jsonl"))
    ap.add_argument("--case-id")
    ap.add_argument("--index", type=int)
    ap.add_argument("--file", help="JSON file containing one submission package (no label)")
    ap.add_argument("--model", default="gpt-4.1-mini")
    ap.add_argument("--compact", action="store_true", help="print decision, issues and check statuses only")
    args = ap.parse_args()

    label = None
    if args.file:
        sub = json.loads(Path(args.file).read_text())
        sub = sub.get("submission", sub)
    else:
        rows = [json.loads(line) for line in Path(args.input).read_text().splitlines() if line.strip()]
        row = next(r for r in rows if r["case_id"] == args.case_id) if args.case_id else rows[args.index or 0]
        sub, label = row["submission"], row.get("label")

    packet = triage_submission(sub, model=args.model).model_dump()
    if args.compact:
        out = {
            "case_id": packet["case_id"],
            "decision": packet["decision"],
            "rationale": packet["decision_rationale"],
            "issues": [{"category": i["category"], "summary": i["summary"]} for i in packet["issues"]],
            "checks": [{"name": c["name"], "status": c["status"], "summary": c["summary"]} for c in packet["checks"]],
            "meta": packet["meta"],
        }
        if label:
            out["label"] = label
        print(json.dumps(out, indent=2))
    else:
        if label:
            packet["_label"] = label
        print(json.dumps(packet, indent=2))


if __name__ == "__main__":
    main()
