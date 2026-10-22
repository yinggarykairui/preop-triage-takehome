# Run 1: local score on `patients_sample_50.jsonl`

Records: 50

| metric | value |
|---|---|
| json_schema_valid | 100.0% |
| decision_match_oracle | 98.0% |
| issue_categories_match_oracle | 96.0% |
| aggregate_local_score_pct | 98.0% |

## Decision confusion matrix (rows = label, columns = predicted)

| label \ predicted | READY | NEEDS_FOLLOW_UP | NOT_CLEARED | INVALID |
|---|---|---|---|---|
| READY | 16 | 1 | 0 | 0 |
| NEEDS_FOLLOW_UP | 0 | 25 | 0 | 0 |
| NOT_CLEARED | 0 | 0 | 8 | 0 |

**False READYs (label not READY, predicted READY): 0** 

## Per-category issue precision / recall

| category | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| REQUIRED_DOCUMENTATION | 12 | 0 | 0 | 100% | 100% |
| REQUIRED_TESTING | 7 | 1 | 0 | 88% | 100% |
| ANTICOAGULATION_MANAGEMENT | 7 | 1 | 0 | 88% | 100% |
| ACUTE_SAFETY_EXCLUSION | 8 | 0 | 0 | 100% | 100% |
| MISSING_REQUIRED_DATA | 9 | 0 | 0 | 100% | 100% |

## Misses (2)

### case_00011 (record 11)
- expected: NEEDS_FOLLOW_UP ['MISSING_REQUIRED_DATA']
- actual:   NEEDS_FOLLOW_UP ['MISSING_REQUIRED_DATA', 'REQUIRED_TESTING']
- label rationale: Procedure date is blank; the H&P just says the laminectomy date is pending OR availability, so I couldn't run any of the window checks. There's also no temperature anywhere in the chart: the structured vitals are BP only, the 02/18 H&P lists just a BP of 117/71, and the 03/09 nursing visit says 'see flowsheet.' The daily aspirin is an antiplatelet, so no anticoagulation plan is needed.
- pipeline rationale: Not ready because of: RULE_2 CBC within window; missing data (temperature).

### case_00037 (record 37)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT']
- label rationale: Anticoagulant here is listed only by brand name, Xarelto, and the 03/27 perioperative medication plan covers it fully: hold for the 2 days before surgery (last dose 04/04) and resume 24-48 hours after once hemostasis is secure. The 10/27/2025 'Admission H&P' is an old establish-care visit, but the 04/01 pre-op H&P is 6 days out, so that's fine. Consent for the tonsillectomy was signed by the patient on 03/31, CBC from 03/29 is well inside 30 days (the 02/14 one is superseded anyway), and the 04/02 pre-op clinic vitals are unremarkable (127/80, 98.4 F).
- pipeline rationale: Not ready because of: RULE_3 Plan for rivaroxaban.

