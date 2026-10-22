# Pipeline: local score on `patients_sample_50.jsonl`

Records: 50

| metric | value |
|---|---|
| json_schema_valid | 100.0% |
| decision_match_oracle | 100.0% |
| issue_categories_match_oracle | 100.0% |
| aggregate_local_score_pct | 100.0% |

## Decision confusion matrix (rows = label, columns = predicted)

| label \ predicted | READY | NEEDS_FOLLOW_UP | NOT_CLEARED | INVALID |
|---|---|---|---|---|
| READY | 17 | 0 | 0 | 0 |
| NEEDS_FOLLOW_UP | 0 | 25 | 0 | 0 |
| NOT_CLEARED | 0 | 0 | 8 | 0 |

**False READYs (label not READY, predicted READY): 0** 

## Per-category issue precision / recall

| category | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| REQUIRED_DOCUMENTATION | 12 | 0 | 0 | 100% | 100% |
| REQUIRED_TESTING | 7 | 0 | 0 | 100% | 100% |
| ANTICOAGULATION_MANAGEMENT | 7 | 0 | 0 | 100% | 100% |
| ACUTE_SAFETY_EXCLUSION | 8 | 0 | 0 | 100% | 100% |
| MISSING_REQUIRED_DATA | 9 | 0 | 0 | 100% | 100% |

## Misses (0)

