# Error analysis

Scored with `scripts/score_local.py` (same metrics as `run_evals.py`, computed locally) against the
50 human labels. "Miss" = any of the three per-case metrics false. Fixes are always to the general
cause; no case IDs or patient names appear in the code.

## Baseline (naive single call, gpt-4.1-mini) — `results/baseline_summary.md`

- Aggregate 73.3%; decision 70%; categories 52%; 1 invalid JSON; **1 false READY** (a missing CBC
  judged READY).
- 11 READY labels predicted NEEDS_FOLLOW_UP: the model invents criteria (A1c, missing CMP for low
  risk, old establish-care H&P) or mis-reads the most-recent vital/lab.
- Category set wrong in 24 cases even when the decision was right: it reports a category per
  observation rather than per failed rule, and labels missing data under the wrong category.
- Not reproducible: a second run changes decisions on several cases.

## Pipeline run 1 (`results/run1_summary.md`) — 98.0%, decision 98%, categories 96%, 0 false READY

Two misses, both traced to **extraction**, none to normalization, rule interpretation or label
disagreement.

| case | expected | got | root cause (group) | general fix |
|---|---|---|---|---|
| case_00011 | NEEDS_FOLLOW_UP [MISSING_REQUIRED_DATA] | + REQUIRED_TESTING | **Extraction.** `procedure_date` is null; the H&P says the date is "to be determined pending OR availability", but the document extractor returned the consent's *signature* date ("signed in clinic 03/07/2026") as a `DATE_STATED` procedure date. With a fake date, the CBC window check ran and failed (31 days). | Prompt now defines a procedure date as an explicit scheduled/target date and excludes signature, visit, service and lab dates. Code rejects a stated date earlier than its own document and treats any verified TBD statement as a conflict (unknown). (A4) |
| case_00037 | READY | NEEDS_FOLLOW_UP [ANTICOAGULATION_MANAGEMENT] | **Extraction.** The anticoagulation extractor flagged the 04/01 H&P line "Continue home medications except as directed by perioperative instructions" as a perioperative plan for Xarelto (deferred, no post-op). Being newer than the real 03/27 plan it was selected as "the most recent plan". | Prompt now requires a plan to give management recommendations for a *named* anticoagulant and names the generic "continue home meds" pattern as not-a-plan. The rule keeps "most recent plan wins" (a later deferral legitimately makes an earlier plan ambiguous) but now cites the earlier complete plan in the evidence so the reviewer sees the conflict. |

### Verification telemetry, run 1 (413 LLM calls, 0 provider failures, 68 unverified quotes)

| unverified field | n | cause | fix |
|---|---|---|---|
| `vitals_deferred_quote` | 52 | model paraphrased ("No vitals recorded in this consultation note") when a note simply lacked vitals; the fact was correctly dropped, no decision impact | schema + prompt now require the quoted phrase and define the flag narrowly |
| `vitals[].quote` | 10 | garbled degree sign (`36.6 \x17C` for `36.6 °C`) — the reading was dropped, the case still had other readings | verifier strips control characters and degree signs; numbers remain exact |
| `procedure_date.quote` | 6 | parentheses dropped around "(date to be determined pending OR availability)" — the TBD statement was dropped | punctuation-insensitive third matching tier (letters, digits, `.`, `%`, `/` preserved) |

None of the 68 unverified quotes could have produced a false READY: by construction an unverified
fact can only move a check toward UNKNOWN.

## Pipeline run 2 (final prompts) — see `results/final_summary.md`

RUN2_PLACEHOLDER

## Where the labels and the policy could be read differently

These are places where I made a call; the labels happened to agree, but a reviewer might not.

- **Missing temperature → MISSING_REQUIRED_DATA.** The policy's "if a required field needed to
  evaluate a rule is missing/unknown → NEEDS_FOLLOW_UP" is read as applying to vitals. A stricter
  reading ("no reading means no exclusion present") would allow READY; that is the unsafe direction
  and the labels reject it (5 cases).
- **A note-reported anticoagulant counts as current** even when absent from the reconciled med
  list (3 cases). The alternative (trust the list) would hide a real Eliquis/Coumadin patient.
- **Establish-care H&Ps count as H&Ps.** The policy does not require the H&P to be a pre-op
  evaluation, so an in-window wellness H&P would pass Rule 1 here. In this sample every such note is
  out of window, so the labels do not distinguish. Flagged in the packet (`is_preop_evaluation`).
- **Missing procedure date does not also trigger REQUIRED_DOCUMENTATION / REQUIRED_TESTING.** The
  windows are *unevaluable*, not failed; one MISSING_REQUIRED_DATA issue names the blocked checks.
  (The labeler did the same in both null-date cases.)
