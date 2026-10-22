"""Pydantic schemas: (1) what the LLM extractors return, (2) the evidence packet.

Extractor models are deliberately flat and fully-required so they can be used
with strict structured outputs. Every positive claim carries a verbatim quote.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. Extraction outputs (LLM -> code)
# ---------------------------------------------------------------------------


class VitalReading(BaseModel):
    kind: Literal["BP", "TEMP"]
    systolic: int | None = Field(description="mmHg, BP only")
    diastolic: int | None = Field(description="mmHg, BP only")
    temperature_value: float | None = Field(description="TEMP only, as written")
    temperature_unit: Literal["F", "C"] | None = Field(description="TEMP only; infer from the degree unit written in the note")
    date: str | None = Field(description="YYYY-MM-DD if the note states the measurement date, else null")
    time: str | None = Field(description="HH:MM (24h) if the note states the clock time of this reading, else null")
    measured_at_this_encounter: bool = Field(description="false for patient-reported home values, historical values, or values quoted from another visit")
    quote: str = Field(description="verbatim substring of the document containing this reading")


class HPFacts(BaseModel):
    is_completed_hp: bool = Field(description="true only if THIS document's text is a completed History and Physical note (any H&P: pre-op, admission, wellness/establish-care). false for notes that merely reference or review an H&P")
    is_preop_evaluation_for_planned_procedure: bool = Field(description="true if the H&P is a pre-operative evaluation for the planned procedure")
    date_of_service: str | None = Field(description="YYYY-MM-DD date of service stated in the H&P text, else null")
    quote: str | None = Field(description="verbatim heading or line showing this is an H&P")
    references_hp_missing: bool = Field(description="true if the text says an H&P is not on file / not yet completed / pending")
    references_hp_missing_quote: str | None


class ConsentFacts(BaseModel):
    is_consent_document: bool = Field(description="true if the text is a surgical/procedure consent form or consent discussion note")
    patient_signed: Literal["SIGNED", "PENDING_OR_UNSIGNED", "NOT_A_CONSENT"] = Field(description="SIGNED only if the PATIENT's signature is documented as completed (e-signed, signed in clinic, signature on file). A physician attestation alone is not a patient signature. Blank line, 'pending', 'not yet signed', 'NOT COMPLETED', 'printed for review' -> PENDING_OR_UNSIGNED")
    procedure_named: str | None = Field(description="procedure the consent covers, as written")
    matches_planned_procedure: bool | None = Field(description="does the procedure on the consent match the planned procedure given in the prompt? null if not a consent")
    signed_date: str | None = Field(description="YYYY-MM-DD the patient signed, if stated")
    quote: str | None = Field(description="verbatim line about the patient signature status")
    references_consent_missing: bool = Field(description="true if a non-consent note says consent is still to be obtained / not yet completed")
    references_consent_missing_quote: str | None


class ProcedureDateFacts(BaseModel):
    status: Literal["DATE_STATED", "UNSCHEDULED_OR_TBD", "NOT_MENTIONED"] = Field(description="DATE_STATED if the text gives a scheduled/target date for the planned procedure")
    date: str | None = Field(description="YYYY-MM-DD, only when status is DATE_STATED")
    quote: str | None = Field(description="verbatim phrase stating the date or that it is TBD")


class DocFacts(BaseModel):
    document_kind: Literal[
        "HISTORY_AND_PHYSICAL",
        "SURGICAL_CONSENT",
        "NURSING_OR_PREADMISSION",
        "ANESTHESIA_EVALUATION",
        "CONSULT_OR_PLAN",
        "OTHER",
    ] = Field(description="what the TEXT is, regardless of the type label")
    hp: HPFacts
    consent: ConsentFacts
    procedure_date: ProcedureDateFacts
    vitals: list[VitalReading] = Field(description="every measured blood pressure and temperature in the text, including rechecks/addenda; do NOT include 'see flowsheet' placeholders or patient-reported home values")
    vitals_deferred_or_not_recorded: bool = Field(description="true if the text says vitals are on a flowsheet, deferred, or not recorded")
    vitals_deferred_quote: str | None


class AnticoagMention(BaseModel):
    drug_as_written: str = Field(description="drug name as written (brand or generic)")
    status: Literal["CURRENTLY_TAKING", "NOT_CURRENTLY_TAKING", "UNCERTAIN", "OTHER"] = Field(description="whether the PATIENT is currently taking this drug at the time of the note: 'maintained on', 'reports taking', 'taking as prescribed' -> CURRENTLY_TAKING; stopped/discontinued/switched off/historical course -> NOT_CURRENTLY_TAKING; patient unable to confirm -> UNCERTAIN; a drug named only as a bridging agent or in perioperative instructions -> OTHER")
    quote: str = Field(description="verbatim substring supporting the status")


class PlanPart(BaseModel):
    present: bool = Field(description="the plan says something about this phase")
    explicit: bool = Field(description="true only if it gives a concrete action with timing (e.g. 'hold 2 days before, last dose 02/26' or 'resume 24-48 hours after' / 'restart POD 1'). 'to be determined', 'will be addressed later', 'per surgical team' -> false")
    quote: str | None = Field(description="verbatim instruction text")


class AnticoagPlan(BaseModel):
    is_perioperative_plan: bool = Field(description="true if this document gives perioperative management recommendations for an anticoagulant")
    drug_named: str | None = Field(description="the anticoagulant the plan is written for, as written")
    pre_op: PlanPart = Field(description="instructions for BEFORE surgery (hold/stop/last dose/bridging start)")
    post_op: PlanPart = Field(description="instructions for AFTER surgery (resume/restart timing, post-op bridging)")
    deferred_to_another_team: bool = Field(description="true if management is left to another team / to be determined")
    deferral_quote: str | None


class AnticoagFacts(BaseModel):
    mentions: list[AnticoagMention] = Field(description="every anticoagulant (warfarin/Coumadin, apixaban/Eliquis, rivaroxaban/Xarelto, dabigatran/Pradaxa, edoxaban/Savaysa, enoxaparin/Lovenox, heparin, fondaparinux) mentioned in relation to the patient. Antiplatelets (aspirin/ASA, clopidogrel/Plavix, ticagrelor) are NOT anticoagulants: do not list them")
    states_patient_not_on_anticoagulant: bool = Field(description="true if the text explicitly says the patient is not on any anticoagulant")
    not_on_anticoagulant_quote: str | None
    plan: AnticoagPlan


# ---------------------------------------------------------------------------
# 2. Evidence packet (code -> nurse reviewer / harness)
# ---------------------------------------------------------------------------

Decision = Literal["READY", "NEEDS_FOLLOW_UP", "NOT_CLEARED"]
CheckStatus = Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]
IssueCategory = Literal[
    "REQUIRED_DOCUMENTATION",
    "REQUIRED_TESTING",
    "ANTICOAGULATION_MANAGEMENT",
    "ACUTE_SAFETY_EXCLUSION",
    "MISSING_REQUIRED_DATA",
]


class Evidence(BaseModel):
    """A pointer a nurse can follow: a structured field path or a doc_id + verbatim quote."""

    source: str = Field(description="e.g. 'procedure.procedure_date', 'labs[2]', 'vitals[0]', 'medications[1]', 'document'")
    value: str | None = None
    doc_id: str | None = None
    doc_type: str | None = None
    date: str | None = None
    quote: str | None = None
    verified: bool = True


class Check(BaseModel):
    rule: str
    name: str
    status: CheckStatus
    category: IssueCategory
    summary: str
    inputs: dict[str, object] = Field(default_factory=dict)
    reference_dates: dict[str, str | None] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknown_key: str | None = Field(default=None, description="which datum is missing when status is UNKNOWN")
    resolution: str | None = None


class Issue(BaseModel):
    category: IssueCategory
    rule: str
    summary: str
    evidence: list[Evidence]
    resolution: str
    # Kept for the stock report viewer, which prints issue['description'].
    description: str = ""


class ProcedureDateSource(BaseModel):
    source: str
    doc_id: str | None = None
    quote: str | None = None


class ReferenceDates(BaseModel):
    procedure_date: str | None
    procedure_date_source: ProcedureDateSource | None
    review_time: str | None
    procedure_risk: str | None


class Meta(BaseModel):
    model: str
    provider: str
    pipeline_version: str
    llm_calls: int = 0
    llm_cache_hits: int = 0
    llm_failures: int = 0
    unverified_quotes: int = 0
    unverified_quote_details: list[str] = Field(default_factory=list)
    documents_extracted: int = 0
    documents_failed: list[str] = Field(default_factory=list)


class TriagePacket(BaseModel):
    """Output contract. `decision`, `issues[].category` and `explanation` keep the harness interface."""

    case_id: str | None
    patient_id: str | None
    decision: Decision
    decision_rationale: str
    explanation: str
    reference_dates: ReferenceDates
    issues: list[Issue]
    checks: list[Check]
    assumptions_applied: list[str]
    meta: Meta
