"""Harness entry point and the shared input/output schemas for the pre-op triage scripts.

`triage_submission` is what run_baseline.py and run_evals.py call. The naive
single-call baseline (prompt + helpers) lives in baseline.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

from preop_triage.schemas import TriagePacket

Decision = Literal["READY", "NEEDS_FOLLOW_UP", "NOT_CLEARED"]
ProcedureRisk = Literal["LOW", "MODERATE", "HIGH"]
IssueCategory = Literal[
    "REQUIRED_DOCUMENTATION",
    "REQUIRED_TESTING",
    "ANTICOAGULATION_MANAGEMENT",
    "ACUTE_SAFETY_EXCLUSION",
    "MISSING_REQUIRED_DATA",
]

# -------------------------
# Schemas
# -------------------------


class PatientName(BaseModel):
    given: str | None = None
    family: str | None = None


class PatientInfo(BaseModel):
    id: str | None = None
    mrn: str | None = None
    name: PatientName | None = None
    dob: str | None = None
    sex: str | None = None


class ProcedureInfo(BaseModel):
    case_id: str | None = None
    procedure_type: str | None = None
    procedure_risk: ProcedureRisk | None = None
    procedure_date: str | None = None
    is_elective: bool | None = None
    location: str | None = None


class BloodPressureVital(BaseModel):
    type: str | None = None
    systolic: float | int | None = None
    diastolic: float | int | None = None
    date: str | None = None
    source: str | None = None


class TemperatureVital(BaseModel):
    type: str | None = None
    value_f: float | int | None = None
    value_c: float | int | None = None
    date: str | None = None
    source: str | None = None


class GenericVital(BaseModel):
    type: str | None = None
    date: str | None = None
    source: str | None = None


Vital = BloodPressureVital | TemperatureVital | GenericVital


class LabResult(BaseModel):
    id: str | None = None
    code: str | None = None
    display: str | None = None
    effective_at: str | None = None
    status: str | None = None
    source: str | None = None


class Medication(BaseModel):
    name: str | None = None
    active: bool | None = None


class Condition(BaseModel):
    name: str | None = None
    active: bool | None = None


class Document(BaseModel):
    doc_id: str | None = None
    type: str | None = None
    date: str | None = None
    author: str | None = None
    text: str | None = None


class SubmissionMetadata(BaseModel):
    submission_received_at: str | None = None
    source_system: str | None = None


class PatientSubmission(BaseModel):
    """Single submission package shape from the take-home prompt."""

    patient: PatientInfo | None = None
    procedure: ProcedureInfo | None = None
    vitals: list[Vital] = Field(default_factory=list)
    labs: list[LabResult] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
    documents: list[Document] = Field(default_factory=list)
    metadata: SubmissionMetadata | None = None


class TriageIssue(BaseModel):
    category: IssueCategory
    evidence: str


class TriageOutput(BaseModel):
    """Structured output contract for triage responses."""

    decision: Decision
    issues: list[TriageIssue] = Field(validation_alias=AliasChoices("issues"))
    explanation: str


def triage_output_json_schema() -> dict[str, object]:
    """Return the JSON schema used for structured model outputs."""

    schema = TriageOutput.model_json_schema()
    return schema


def triage_submission(
    submission: dict[str, object] | PatientSubmission,
    *,
    model: str,
) -> TriagePacket:
    """Harness entry point: normalize -> LLM extraction -> verify -> deterministic rules.

    The returned packet keeps `decision`, `issues[].category` and `explanation`, so the
    harness and the report viewer keep working. The naive single-call baseline lives in
    baseline.py for comparison.
    """

    from preop_triage.pipeline import triage

    if isinstance(submission, PatientSubmission):
        payload = submission.model_dump()
    else:
        payload = PatientSubmission.model_validate(submission).model_dump()
    return triage(payload, model=model)
