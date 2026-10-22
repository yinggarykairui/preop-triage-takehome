# Naive baseline (gpt-4.1-mini): local score on `patients_sample_50.jsonl`

Records: 50

| metric | value |
|---|---|
| json_schema_valid | 98.0% |
| decision_match_oracle | 70.0% |
| issue_categories_match_oracle | 52.0% |
| aggregate_local_score_pct | 73.33% |

## Decision confusion matrix (rows = label, columns = predicted)

| label \ predicted | READY | NEEDS_FOLLOW_UP | NOT_CLEARED | INVALID |
|---|---|---|---|---|
| READY | 6 | 11 | 0 | 0 |
| NEEDS_FOLLOW_UP | 1 | 24 | 0 | 0 |
| NOT_CLEARED | 0 | 2 | 5 | 1 |

**False READYs (label not READY, predicted READY): 1** case_00026

## Per-category issue precision / recall

| category | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| REQUIRED_DOCUMENTATION | 8 | 6 | 4 | 57% | 67% |
| REQUIRED_TESTING | 7 | 5 | 0 | 58% | 100% |
| ANTICOAGULATION_MANAGEMENT | 6 | 10 | 1 | 38% | 86% |
| ACUTE_SAFETY_EXCLUSION | 5 | 1 | 3 | 83% | 62% |
| MISSING_REQUIRED_DATA | 3 | 0 | 6 | 100% | 33% |

## Misses (27)

### case_00000 (record 0)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT']
- label rationale: Xarelto 20 mg isn't on the med list, but the 02/26 pre-admission nursing note says she's taking it, so I treated her as anticoagulated. The 02/20 cardiology consult covers it: hold Xarelto for the 2 days before surgery (last dose 02/26) and resume 24-48 hours after. Pre-op H&P from 02/21 (8 days out), consent for carpal tunnel release signed by the patient 02/27, CBC 02/11 (18 days) and latest vitals of 119/73 and 97.9 F are all fine.
- pipeline rationale: The patient is on the anticoagulant Xarelto, but the active medication list does not include this anticoagulant, and there is no clearly documented perioperative anticoagulation management plan in the provided documentation. While the cardiology consultation discusses perioperative hold instructions, there is no explicit clear perioperative anticoagulation plan documented in a surgical or pre-op note. Additionally, the required CBC was done within 30 days for a low risk procedure, required documentation (H&P within 30 days and signed surgical consent) are present, and no acute safety exclusions are noted.

### case_00002 (record 2)
- expected: NOT_CLEARED ['ACUTE_SAFETY_EXCLUSION', 'REQUIRED_DOCUMENTATION']
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT', 'REQUIRED_DOCUMENTATION']
- label rationale: Two separate problems here. At the 03/01 nursing intake he was running 38.6 C (101.5 F) and reported chills and malaise since the day before, so that's over the fever threshold and he's not cleared. The consent is also incomplete: the portal e-signature request went out 02/24 and still shows NOT COMPLETED. The daily aspirin is an antiplatelet, so there's no anticoagulation plan needed.
- pipeline rationale: The patient has a valid H&P completed within 30 days and vitals do not show acute safety exclusions. CBC testing within 30 days exists for the low risk procedure. However, the signed surgical consent is not completed by the patient as of the latest note, which is required for clearance. Additionally, the patient is on ASA 81 mg daily (an anticoagulant in this context) but there is no documented perioperative anticoagulation management plan. These missing items require follow-up before clearance.

### case_00003 (record 3)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT']
- label rationale: She's on Eliquis plus baby aspirin; the aspirin doesn't need a plan, and the 02/23 hematology consult handles the Eliquis by brand name (hold for 2 days before surgery, resume 48 hours post-op). H&P dated 02/16 is 16 days out, consent was signed by the patient 02/19, and the CBC from 02/24 is well within 30 days for a low-risk hernia repair. Most recent vitals are from the 03/02 nursing intake: BP 116/76 and T 37.0 C (98.6 F).
- pipeline rationale: The pre-op package includes a history and physical completed on 2026-02-16 and a signed surgical consent on 2026-02-19, both within 30 days of the procedure date (2026-03-04), satisfying documentation requirements. The procedure is LOW risk and requires a CBC within 30 days. The most recent CBC is dated 2026-02-24, which is within 30 days, meeting the testing requirement. However, the patient is taking the anticoagulant Eliquis, and while a perioperative anticoagulation plan is documented on 2026-02-23, the last dose timing (planned last dose 03/01/2026 before 03/04/2026 surgery) needs confirmation of adherence and clarity on perioperative management timing regarding the procedure date. Furthermore, there is no CBC result timestamp confirming it is final and timely relative to the surgery date, and mild uncertainty remains about the antifactor Xa management plan documentation specificity. Vital signs show no acute safety exclusions. Due to the need for confirmation and possible clarification around the anticoagulation management plan, the patient requires follow-up before clearance.

### case_00004 (record 4)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT', 'REQUIRED_DOCUMENTATION', 'REQUIRED_TESTING']
- label rationale: The newest CBC (02/10) is marked entered-in-error, so I went back to the 02/09 CBC, which is 24 days out and fine for a moderate-risk thyroidectomy. Warfarin is covered by the 02/24 hematology consult: stop 5 days before with enoxaparin bridging, resume the evening of surgery. H&P from 02/24, consent signed by the patient 03/03, and the 03/02 intake vitals (98.1 F, repeat BP 140/78) all check out.
- pipeline rationale: The patient is scheduled for a moderate risk procedure (thyroidectomy), requiring a CBC within 30 days of the procedure date (03/05/2026). The most recent valid CBC is from 02/09/2026, within the 30-day window, so CBC requirement is met. CMP is not required for moderate risk procedures. H&P exists, dated 02/24/2026, within 30 days, and surgical consent was signed on 03/03/2026, meeting documentation requirements. No acute safety exclusions present: recent BP readings (133/84, 138/76) and temperature (98.6 F) are normal. The patient is on warfarin; a perioperative anticoagulation plan is required and documented clearly in the hematology consultation dated 02/24/2026 with detailed management plan. However, the hematology consultation notes to stop warfarin 5 days before surgery and last dose on 02/27/2026 for a surgery on 03/05/2026, but the last warfarin dose is notably before the H&P (02/24/2026) and consent (03/03/2026), patient status on 03/05/2026 is uncertain regarding adherence to the plan and INR check. The policy requires the anticoagulation plan to be documented and clear, but there is no confirmation that the INR was checked the day before surgery with goal <1.5 and that bridging was done as recommended. This missing verification of the implementation of the anticoagulation plan just prior to the surgery date leads to uncertainty. Therefore, follow-up is needed to confirm appropriate perioperative anticoagulation management implementation immediately prior to surgery.

### case_00005 (record 5)
- expected: NOT_CLEARED ['ACUTE_SAFETY_EXCLUSION']
- actual:   INVALID []
- label rationale: Structured vitals look fine (119/78 on 03/01), but the 03/03 nursing pre-procedure note is more recent and has BP 157/117. A diastolic of 117 is over the 110 cutoff, so this one's held. Paperwork and labs are otherwise complete: H&P 02/14, signed consent 02/22, and CBC 02/22 and CMP 02/23 are both within 14 days of the 03/06 colectomy.
- pipeline rationale: None

### case_00007 (record 7)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['REQUIRED_DOCUMENTATION', 'REQUIRED_TESTING']
- label rationale: At first glance the consent looks like a problem, since the 02/18 form says the patient signature is pending (she wanted to review it with family). But she signed a new consent for the hepatic lobectomy on 03/03, and that one supersedes it. For a high-risk case the labs are tight and they pass: CBC 03/04 and CMP 03/06 are both within 14 days. The pre-op H&P from 02/12 is 24 days out. Vitals at the 03/06 nursing visit were 37.2 C (99.0 F) and 121/80.
- pipeline rationale: The patient has a valid History and Physical within 30 days and a signed surgical consent form dated 03/03/2026. The procedure is high risk, requiring CBC and CMP within 14 days. The most recent CMPs are on 2026-02-15 and 2026-03-06 (both valid). The most recent CBC is from 2026-03-04, which is within 14 days. No anticoagulants are listed, so no anticoagulation plan is required. Vital signs do not reveal any acute safety exclusions (BP and temperature well within limits). However, the CBC test result on 2026-02-05 is outside the 14-day window, but there is a valid CBC on 2026-03-04 which is acceptable. The issue is the signed surgical consent form: there are two consents, but only one is signed and dated 03/03/2026, which is valid. The other consent is unsigned and pending. Since a signed surgical consent exists, this criterion is met. There is however no documentation explicitly confirming whether the perioperative anticoagulation management plan is documented. Because the patient is not on anticoagulants, the policy does not require a plan. All criteria are met based on provided information, but there is no explicit mention of a perioperative anticoagulation plan documented. Since the patient is not on anticoagulants, that does not cause a failure. Overall, all criteria met for readiness except the CBC dated 02/05/2026 is outside the required window, but the 03/04/2026 CBC is within window and valid. Therefore, the patient is READY for surgery.

### case_00008 (record 8)
- expected: NEEDS_FOLLOW_UP ['REQUIRED_DOCUMENTATION']
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT', 'REQUIRED_DOCUMENTATION']
- label rationale: There's no surgical consent anywhere in the package. The 02/25 H&P even says consent is still to be obtained by the surgical team and hasn't been done yet. Everything else is fine for a high-risk case: H&P 12 days out, CBC 03/04, CMP 02/27, and normal vitals. He takes aspirin only, so no anticoagulation plan is needed.
- pipeline rationale: The patient is scheduled for a high-risk procedure (hepatic lobectomy), which requires a CBC and CMP within 14 days prior to the procedure date. Both labs are present and recent enough (CBC on 2026-03-04, CMP on 2026-02-27). The History & Physical (H&P) was completed within 30 days (dated 2026-02-25). However, the signed surgical consent is missing as per the H&P note stating it has not yet been completed. The patient is taking aspirin, which is an anticoagulant requiring a perioperative anticoagulation plan but no such plan is documented. Vital signs show no acute safety exclusions (BP and temperature within acceptable limits). Therefore, follow-up is needed for missing signed surgical consent and documented perioperative anticoagulation plan.

### case_00009 (record 9)
- expected: NEEDS_FOLLOW_UP ['MISSING_REQUIRED_DATA', 'REQUIRED_TESTING']
- actual:   NEEDS_FOLLOW_UP ['REQUIRED_TESTING']
- label rationale: The CBC is from 02/23, which is 15 days before the 03/10 CABG. For a high-risk case the limit is 14, so it's one day too old. The CMP from 03/04 is fine. Temperature is also missing everywhere: the structured vitals, the 02/26 H&P and the 03/08 nursing intake all have BP but no temp.
- pipeline rationale: The patient requires a History and Physical (H&P) completed within 30 days before the procedure date 03/10/2026. The latest H&P document is dated 02/26/2026, which is within 30 days, so this criterion is met. Signed Surgical Consent form is present, signed on 03/01/2026, meeting the requirement. For a HIGH risk procedure, both CBC and CMP must be done within 14 days before the procedure date. The CBC was performed on 02/23/2026, which is 16 days before the procedure date, thus outside the 14-day window, and the CMP was done on 03/04/2026, within 14 days. Vitals do not show acute exclusions (most recent BP 131/78, below exclusion thresholds). There is no anticoagulant medication active, so anticoagulation management does not apply. Since the CBC is outside the required time window, the patient needs follow-up testing before proceeding.

### case_00013 (record 13)
- expected: NEEDS_FOLLOW_UP ['MISSING_REQUIRED_DATA', 'REQUIRED_DOCUMENTATION']
- actual:   NEEDS_FOLLOW_UP ['REQUIRED_DOCUMENTATION']
- label rationale: High-risk esophagectomy on 03/14 with no H&P anywhere in the chart. The 03/07 anesthesia note even says it isn't on file yet and that primary care was contacted. No temperature was recorded either: structured vitals are BP only and the 03/12 pre-admission visit just says 'see flowsheet.' Signed consent plus the 03/11 CBC and 03/07 CMP (7 days out) are all fine.
- pipeline rationale: The patient has a signed surgical consent and a recent CBC (2026-03-11) and CMP (2026-03-07), meeting test requirements for a HIGH risk procedure. Blood pressure and temperature measurements show no acute safety exclusions. However, the History and Physical (H&P) documentation is missing; the anesthesia note specifically states 'H&P: not yet on file for this surgical episode; primary care office contacted to complete.' This missing required documentation causes the pre-op package to require follow-up before clearance.

### case_00014 (record 14)
- expected: NEEDS_FOLLOW_UP ['REQUIRED_DOCUMENTATION']
- actual:   NEEDS_FOLLOW_UP []
- label rationale: The only H&P is Dr. Carter's from 02/12, which is 31 days before the 03/15 tonsillectomy, one day past the 30-day limit. Everything else checks out: consent e-signed 03/11, CBC 02/18 (25 days, fine for low risk), and latest vitals 128/72 and 98.5 F on 03/10.
- pipeline rationale: Required CBC test is slightly out of the 30-day window, being done on 2026-02-18 while surgery is on 2026-03-15, which is 25 days difference and acceptable. CMP not required for LOW risk procedure. History and Physical (H&P) is completed within 30 days. Signed surgical consent is present. No anticoagulants reported, so no anticoagulation plan needed. No acute safety exclusions in vital signs. However, CMP is not required for LOW risk procedures, so missing CMP is not an issue. All required criteria are met except that the CBC was done 25 days prior which is within 30-day window. However, upon rechecking dates, CBC on 02/18/2026 to surgery date 03/15/2026 is exactly 25 days difference, which is within required window. Therefore all criteria are met and no exclusions present. Thus, patient is READY.

### case_00015 (record 15)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP []
- label rationale: There's a 184/112 from the 03/04 primary care visit, which would have held this, but it isn't the latest reading. The 03/11 cardiology BP was 123/70 with a temp of 97.8 F, so it doesn't block. The 02/23 pre-op H&P is 21 days out (the 06/2025 one is just old), the CBC from 02/27 is 17 days out, and the consent was signed 03/06.
- pipeline rationale: The patient has an H&P completed within 30 days of the procedure date and a signed surgical consent on file. The procedure is LOW risk, requiring a CBC within 30 days, and a CBC from 2026-02-27 is available and within the window. There is no record of CMP, but CMP is required only for HIGH risk procedures, so not needed here. The most recent blood pressure reading within the review period (2026-03-11) is 123/70, which is below acute safety exclusion thresholds. The patient is not taking any anticoagulants; therefore, no anticoagulation plan is required. However, there is a blood pressure reading on 2026-03-04 with systolic 184 and diastolic 112, both exceeding acute safety exclusion thresholds. Since acute safety exclusions are based on the most recent vital signs, and there is a more recent BP reading on 2026-03-11 which is normal, the acute exclusion does not apply. No clear evidence of perioperative anticoagulation plan is necessary. However, CBC lab result's effective date is 2026-02-27, which is 18 days prior to procedure on 2026-03-16, within the 30-day window for LOW risk procedures. The only missing element is a perioperative anticoagulation plan documentation; since the patient is not on anticoagulants, this is not required. All required documents and labs are present and within time limits. The only concern is outdated CBC on 02/10/2026, but the more recent CBC on 02/27/2026 is valid. Therefore, all criteria appear satisfied. However, since the patient's most recent blood pressure was elevated on 03/04/2026 (184/112), and some protocols might require more stable readings closer to the date, but the policy states to use the most recent vital signs (2026-03-11) which are normal, so no exclusion applies. The policy states if a required field is missing or unknown, then needs follow up. All required fields seem present, but the CBC timing is borderline. Since the CBC was within 30 days and the H&P is within 30 days, consent is signed, no anticoagulant use, no acute exclusions at most recent measurement, the decision should be READY.

### case_00016 (record 16)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['ACUTE_SAFETY_EXCLUSION']
- label rationale: The 03/15 nursing assessment starts with 189/112 at 08:06, but the 08:30 addendum re-measured 137/78 after 24 minutes in a quiet room. That's the most recent BP, so it isn't a hold. Temp was 37.1 C (98.8 F). H&P 02/21 (24 days), CBC 03/02, consent signed 03/13, and the ASA 81 is an antiplatelet, so no anticoag plan is needed.
- pipeline rationale: There is an acute safety exclusion on 2026-03-15 with a recent blood pressure of 189/112 mmHg, which exceeds the policy thresholds (systolic >=180 or diastolic >=110). This requires clearance before proceeding.

### case_00020 (record 20)
- expected: NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT']
- actual:   NEEDS_FOLLOW_UP []
- label rationale: He's on Coumadin, and the 03/15 cardiology note covers the front end well: stop warfarin 5 days out (last dose 03/15), INR check the day before, enoxaparin bridge. The post-op side is just "will be addressed after surgery," though, so nobody has said when to restart the warfarin. That needs to come back before the 03/21 knee. The daily aspirin doesn't count here, and the pre-op H&P (03/09), signed consent and CBC from 02/25 (24 days out) are all fine.
- pipeline rationale: The patient has a valid and recent H&P (03/09/2026) and signed surgical consent (03/10/2026). For the planned moderate risk procedure, a CBC within 30 days is required; the most recent CBC is from 02/25/2026, which is 24 days prior to the procedure date 03/21/2026, so this meets the requirement. There are no high-risk labs requiring BMP within 14 days, and BMP is also available from 03/12/2026. The patient is on warfarin (Coumadin) anticoagulation; a perioperative anticoagulation plan must be documented and clear. The cardiology note dated 03/15/2026 provides detailed perioperative anticoagulation management recommendations, satisfying this requirement. Vital signs show no exclusions. However, the most recent CBC is borderline but within 30 days, so acceptable. All documentation is present and current, testing criteria are met, anticoagulation plan is clear, and no acute exclusions present. Therefore, the patient is READY for surgery.

### case_00021 (record 21)
- expected: NEEDS_FOLLOW_UP ['MISSING_REQUIRED_DATA', 'REQUIRED_DOCUMENTATION']
- actual:   NEEDS_FOLLOW_UP ['REQUIRED_DOCUMENTATION']
- label rationale: Two gaps. The only real pre-op H&P is dated 02/06, which is 44 days before the 03/22 carpal tunnel release, well outside 30 days (the 07/11/2025 wellness visit is even older). There's also no temperature anywhere: the structured vitals only have BPs, and the H&P exam lists just a BP. Consent is signed and the 02/26 CBC is within window.
- pipeline rationale: The History and Physical documentation within 30 days of the procedure date is missing. The most recent H&P is dated 2026-02-06, which is 44 days before the procedure date of 2026-03-22, exceeding the 30-day window required by policy. Although the surgical consent is present and vital signs do not show acute safety exclusions, and the procedure risk is low with CBC needed within 30 days, the CBC test within 30 days is missing as the latest CBC is from 2026-02-26, which is 25 days prior to procedure date and acceptable. No anticoagulant medications or plans documented, so no anticoagulation management follow-up needed. The missing valid H&P requires follow-up.

### case_00024 (record 24)
- expected: NEEDS_FOLLOW_UP ['REQUIRED_DOCUMENTATION']
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT']
- label rationale: The only consent on file is a signed cardiothoracic form for coronary artery bypass grafting (03/15), but she's scheduled for a thyroidectomy, so there's no consent for this procedure. Rest of the package is fine. The 03/08 pre-op H&P is 17 days out, CBC from 03/16, vitals normal, and ASA 81 is just an antiplatelet.
- pipeline rationale: The required History and Physical (H&P) completed on 03/08/2026 is within 30 days of the procedure date (03/25/2026) and considered valid. A signed surgical consent exists dated 03/15/2026. The procedure risk is MODERATE, so a CBC within 30 days is required; the CBC on 03/16/2026 meets this criteria. No CMP is required for moderate risk. There are no acute safety exclusion vital signs (the most recent blood pressure is 127/77 and temperature 98.8F). The patient is currently taking ASA 81 mg daily, which is an anticoagulant/antiplatelet agent; however, there is no documented perioperative anticoagulation plan provided in the documentation reviewed. Therefore, per policy, follow-up is needed to obtain a clear anticoagulation management plan prior to scheduling surgery.

### case_00025 (record 25)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP []
- label rationale: He's on aspirin plus clopidogrel after a 2023 stent, and those are both antiplatelets, not anticoagulants. The 03/16 cardiology note confirms he's not on any anticoagulant and already has a hold/resume plan for the clopidogrel anyway. H&P 03/08 (18 days out), consent signed 03/21, CBC 03/13 and vitals (130/70, 98.6 F) are all good, so this one's ready.
- pipeline rationale: The patient has documented History and Physical (H&P) dated 03/08/2026 and a signed surgical consent dated 03/21/2026, both within 30 days of the scheduled procedure date 03/26/2026, satisfying documentation requirements (Rule 1). The procedure is LOW risk, so a CBC within 30 days is required. The most recent CBC is dated 03/13/2026, within 30 days of the procedure date, fulfilling testing requirement (Rule 2). No CMP test is required for LOW risk procedures. The patient is on aspirin and clopidogrel (dual antiplatelet therapy), which are antiplatelet agents, not anticoagulants; cardiology note states the patient is not on any anticoagulant, so anticoagulation management plan per Rule 3 is not applicable. Recent vitals show no acute safety exclusions (BP <180/110, temp <100.4F) per Rule 4. However, the CBC test documentation does not specify a final result status explicitly; if the lab status 'final' indicates completion, it is sufficient. The main issue is that although the CBC lab exists, the actual test result details (date reference is UTC but the document time zones are not clear) and completeness are ambiguous; also no CMP test exists but not required for LOW risk. Since all required data appear present and no exclusions found, the only possible outstanding is confirmation of CBC result adequacy. Given the data, the case is READY unless there is missing lab detail; if we assume lab completion is acceptable, decision would be READY. However, the policy states: "If a required field needed to evaluate a rule is missing/unknown -> NEEDS_FOLLOW_UP." Lab result details are not fully shown. Therefore, prudent action is NEEDS_FOLLOW_UP to ensure lab results are available and acceptable before clearance.

### case_00026 (record 26)
- expected: NEEDS_FOLLOW_UP ['REQUIRED_TESTING']
- actual:   READY ['REQUIRED_TESTING']
- label rationale: Low-risk tonsillectomy on 03/27. The only labs on file are a TSH, a UA and an A1c, and there's no CBC at all, so we need one. I checked the dabigatran carefully and it's fine: the 03/17 perioperative medication plan says to hold it 3 days (last dose 03/23) and restart on post-op day 1. The H&P from 03/17 and the consent signed 03/16 are also good.
- pipeline rationale: All required documentation is present and up-to-date: a History & Physical dated 03/17/2026 (within 30 days of procedure 03/27/2026) and a signed Surgical Consent dated 03/16/2026. For the low-risk tonsillectomy, a CBC within 30 days is required. Although CBC test is not explicitly listed, evaluation notes mention labs per protocol with results to be reviewed, but since CBC result is not provided, needs follow-up would be usual; however, since no CBC test data is present, this is a gap, but per policy if required field is missing to evaluate a rule then NEEDS_FOLLOW_UP is indicated. However, no CBC lab is found, so this is missing required test and needs follow-up. But since the prompt asks strictly per policy, missing required test is NEEDS_FOLLOW_UP, but the user wants readiness evaluation so must mark NEEDS_FOLLOW_UP. Vital signs show no acute safety exclusions. Patient is on dabigatran anticoagulant and a perioperative medication plan is documented clearly. Therefore, missing CBC test requires follow-up before clearance.

### case_00028 (record 28)
- expected: NOT_CLEARED ['ACUTE_SAFETY_EXCLUSION', 'REQUIRED_DOCUMENTATION']
- actual:   NOT_CLEARED ['ACUTE_SAFETY_EXCLUSION']
- label rationale: Most recent BP is 148/110 from the 03/24 pre-op clinic. A diastolic of exactly 110 meets the cutoff, so this isn't cleared, and there's no later reading to override it. On top of that, the consent was sent to the patient portal on 03/26 and still shows as not completed, so there's no patient signature. Temp was 99.1 F, fine. H&P (03/15) and CBC (03/08) are within window.
- pipeline rationale: The patient's most recent blood pressure reading on 2026-03-24 shows a diastolic pressure of 110 mmHg, which meets the acute safety exclusion criteria (diastolic BP >=110 mmHg). Therefore, the patient is not cleared for surgery at this time.

### case_00029 (record 29)
- expected: NEEDS_FOLLOW_UP ['MISSING_REQUIRED_DATA']
- actual:   NEEDS_FOLLOW_UP ['REQUIRED_DOCUMENTATION']
- label rationale: Procedure risk is blank for the AAA repair, and the 03/10 H&P confirms the surgical team hasn't assigned a risk category yet. Without a risk level we can't tell which lab rules apply, so it needs follow-up. Everything else looks complete: H&P 20 days out, consent signed 03/25, CBC 03/25 and CMP 03/28, and normal vitals.
- pipeline rationale: The surgical risk category for the abdominal aortic aneurysm repair procedure has not been assigned, which is necessary to determine required preoperative testing (CBC and CMP timing). The History and Physical was completed within 30 days and a signed surgical consent is present. Required labs CBC and CMP have been performed recently. No anticoagulants are noted, so anticoagulation management is not required. No acute safety exclusions present. Further information on procedure risk is needed to confirm cleared status.

### case_00031 (record 31)
- expected: NOT_CLEARED ['ACUTE_SAFETY_EXCLUSION', 'REQUIRED_DOCUMENTATION']
- actual:   NOT_CLEARED ['ACUTE_SAFETY_EXCLUSION']
- label rationale: Vitals aren't listed in date order, but the latest temperature is 101.8 F from the 03/27 pre-op clinic visit (the 03/30 pre-admission note just says 'see flowsheet'), so this one isn't cleared for fever. The thyroidectomy consent from 03/28 was also only printed for review and never signed by the patient.
- pipeline rationale: The patient has a recent temperature reading of 101.8 F on 2026-03-27, which exceeds the acute safety exclusion threshold (>100.4 F). Therefore, the patient is not cleared for surgery at this time.

### case_00032 (record 32)
- expected: NOT_CLEARED ['ACUTE_SAFETY_EXCLUSION', 'REQUIRED_TESTING']
- actual:   NEEDS_FOLLOW_UP ['REQUIRED_TESTING']
- label rationale: BP at the 03/31 pre-admission visit was 196/110 on arrival, and the recheck 32 minutes later was still 181/98, so the most recent reading is over the 180 systolic line and she's not cleared. On top of that, there's no CBC on file at all, just a TSH from 03/07. The aspirin 81 mg isn't an anticoagulation issue.
- pipeline rationale: The required CBC test is missing for the LOW risk knee arthroscopy procedure. The most recent available lab is a TSH test from 2026-03-07, which does not fulfill the CBC requirement within 30 days of the procedure date (2026-04-02). Although all other documentation (H&P dated 2026-03-25 and signed consent on 2026-03-31) and vitals are acceptable with no acute safety exclusions, the lack of required CBC testing prevents clearance.

### case_00033 (record 33)
- expected: NEEDS_FOLLOW_UP ['MISSING_REQUIRED_DATA']
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT']
- label rationale: Coumadin 5 mg daily is on the med list, but its active status is blank, and at the 03/31 pre-admission visit the patient couldn't confirm whether she's still taking it (pharmacy fill history was requested). Until someone confirms whether she's on warfarin, we can't tell if a peri-op plan is needed. Everything else is in order: H&P 03/09 (25 days out), CBC 03/12, and consent signed 03/24.
- pipeline rationale: The patient has a History and Physical from 03/09/2026, within 30 days of the procedure date 04/03/2026, and a signed surgical consent from 03/24/2026, so documentation requirements are met. The procedure risk is MODERATE, requiring a CBC within 30 days, and the patient has a CBC from 03/12/2026, which is within the window, so testing requirements are met. However, there is uncertainty about anticoagulation management; the patient possibly takes Coumadin (Warfarin), but active status is unknown (active: null) and no documented perioperative anticoagulation plan is provided. Therefore, per policy, a perioperative anticoagulation plan must be documented if anticoagulants are used, otherwise follow-up is needed.

### case_00034 (record 34)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['REQUIRED_DOCUMENTATION', 'REQUIRED_TESTING']
- label rationale: Everything's in order for the 04/04 hernia repair. The H&P that counts is the 03/24 pre-op evaluation, 11 days out (the 06/2025 wellness visit is too old but doesn't matter). CBC 03/24, patient-signed consent 03/25, and the latest vitals of 132/78 and 99.0 F on 03/30 are fine. The BMP isn't needed for a low-risk case.
- pipeline rationale: The History and Physical (H&P) documentation must be completed within 30 days of the procedure date (2026-04-04). The most recent H&P is dated 2026-03-24, which is within 30 days, so it meets the requirement. The Signed Surgical Consent exists from 2026-03-25, so consent is adequate. The procedure risk is LOW, so a CBC within 30 days is required. The CBC date is 2026-03-24, which is within 30 days and acceptable. The patient is not documented on an anticoagulant, so no anticoagulation plan is required. Vital signs do not demonstrate acute safety exclusions (all blood pressures and temperature are below thresholds). However, the Basic Metabolic Panel (CMP) is not required for low risk, so its older date is acceptable. 

However, the CBC lab result is missing active lab values or status details in the submission—only code and date are present with no reported status as final or values confirmed. This may be insufficient to confirm the adequacy of the CBC test per policy. Additionally, no explicit confirmation of the CBC results (actual lab data) is given beyond the lab existence. Since key evaluation data for the CBC test completeness and finality is missing or not fully verifiable and considering no recent vitals on day of submission or closer to procedure date were provided, further confirmation is needed before clearance. Thus, "NEEDS_FOLLOW_UP" is appropriate due to incomplete data verification to fully fulfill Rule 2 documentation criteria.

### case_00037 (record 37)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT', 'REQUIRED_DOCUMENTATION', 'REQUIRED_TESTING']
- label rationale: Anticoagulant here is listed only by brand name, Xarelto, and the 03/27 perioperative medication plan covers it fully: hold for the 2 days before surgery (last dose 04/04) and resume 24-48 hours after once hemostasis is secure. The 10/27/2025 'Admission H&P' is an old establish-care visit, but the 04/01 pre-op H&P is 6 days out, so that's fine. Consent for the tonsillectomy was signed by the patient on 03/31, CBC from 03/29 is well inside 30 days (the 02/14 one is superseded anyway), and the 04/02 pre-op clinic vitals are unremarkable (127/80, 98.4 F).
- pipeline rationale: The patient has an updated H&P dated 2026-04-01 (within 30 days) and a signed surgical consent dated 2026-03-31. The procedure is LOW risk, requiring a CBC within 30 days, which is present dated 2026-03-29. However, the most recent CMP is from 2026-03-31, which is not required for LOW risk. The patient is on an anticoagulant (Xarelto), and a clear perioperative anticoagulation management plan is documented dated 2026-03-27. Vital signs show no acute safety exclusions. The only outstanding issue is that the CBC date is 2026-03-29, which is 9 days before the procedure on 2026-04-07 and therefore valid, so no testing issues. Since no issues were found, but given the policy states if a required field is missing or unknown to request follow-up and there is no explicit confirmation of no acute infection or URI symptoms on day of procedure, the safest position per policy is to consider as NEEDS_FOLLOW_UP to confirm no acute URI symptoms on day of procedure or last 48 hrs status as the nursing note from 2026-04-04 mentions no recent symptoms but maybe additional clarification needed for final clearance.

### case_00039 (record 39)
- expected: NEEDS_FOLLOW_UP ['MISSING_REQUIRED_DATA']
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT', 'REQUIRED_DOCUMENTATION']
- label rationale: Procedure risk is blank for the 04/09 CABG, and even the 03/15 H&P says the surgical team hasn't assigned a risk category yet, so this needs follow-up. Otherwise the chart looks complete: H&P 25 days out, consent e-signed 03/28, and the CBC 04/05 and CMP 03/28 would meet even the high-risk 14-day window.
- pipeline rationale: The History and Physical (H&P) is completed within 30 days and signed, the Surgical Consent is signed and present, and recent CBC and CMP labs are done. The procedure is coronary artery bypass grafting (CABG), a high-risk procedure requiring CBC and CMP within 14 days, which are available within that window. Vital signs show no acute safety exclusions. However, the procedure risk category has not been assigned, which is required to fully apply the testing criteria per policy. Also, there is no documentation of a perioperative anticoagulation plan, and it is unclear if the patient is on anticoagulants. Hence, follow-up is needed to assign the procedure risk category and clarify anticoagulation management plan to complete triage evaluation.

### case_00043 (record 43)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['REQUIRED_TESTING']
- label rationale: Warfarin (Coumadin) shows up in the med list but it's marked inactive, and the 03/26 H&P says hematology stopped it in early 2020 and she isn't anticoagulated now, so no stop/restart plan is needed. H&P is 18 days out, CBC from 03/28 is 16 days, consent was signed 04/04, and the 04/11 nursing visit has BP 130/72 and temp 98.6 F.
- pipeline rationale: The patient has required documentation for H&P completed on 2026-03-26 (within 30 days) and signed surgical consent on 2026-04-04. The procedure risk is LOW, which requires a CBC within 30 days. A CBC result exists dated 2026-03-28 but no lab details confirm if the CBC is complete or final numeric values. CMP is not required for low risk. Patient is not currently on anticoagulants, so no anticoagulation plan is necessary. Latest vitals show no acute safety exclusions. However, the CBC test document lacks detail and no CMP was provided or indicated. To definitively clear the patient, confirmation of CBC comprising required parameters is necessary; the lack of verified CBC results triggers a follow-up need.

### case_00049 (record 49)
- expected: READY []
- actual:   NEEDS_FOLLOW_UP ['ANTICOAGULATION_MANAGEMENT']
- label rationale: The first consent (02/21) still says 'patient signature: pending' because she took the form home to review with family. A new consent was signed in clinic on 03/03, before the 03/05 hip replacement, so consent is covered. She's on aspirin 81 only, which doesn't need an anticoagulation plan. H&P from 02/17 is 16 days out, CBC from 02/25 is 8 days, and the 03/02 recheck BP was 127/75.
- pipeline rationale: The patient has a valid History and Physical within 30 days (dated 02/17/2026) and a signed surgical consent (dated 03/03/2026). The procedure is moderate risk, requiring a CBC within 30 days. The most recent CBC is from 02/25/2026, which is within the 30-day window. Vital signs show no acute safety exclusions. The patient is taking aspirin (an anticoagulant) but no perioperative anticoagulation management plan is documented, which is required. Also, multiple consent forms exist but only one is signed and current (the 03/03/2026 consent). Therefore, the case needs follow-up to clarify the anticoagulation management plan and confirm surgical consent.

