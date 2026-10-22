"""LLM extraction, per document and per concern. The LLM reads; it never decides.

Two extractors run on each document:
  1. DocFacts     - what the document is, H&P / consent facts, procedure date, vitals in text
  2. AnticoagFacts - anticoagulant mentions and the perioperative plan (only on documents
                     whose text mentions anticoagulation at all; code-side prefilter)

Every quote is verified against the document. If any quote fails, the extractor is
re-run once with the failures listed; whatever still fails is marked unverified.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .llm import CachedLLM, LLMError
from .normalize import mentions_anticoagulation
from .schemas import AnticoagFacts, DocFacts
from .verify import quote_in_text

DOC_FACTS_INSTRUCTIONS = """You are a careful medical-records reader. You extract facts from ONE clinical document for a pre-operative scheduling review. You do not make clearance decisions.

Rules:
- Decide what the document IS from its text, not from the 'type' label, which may be wrong or vague.
- Quotes must be copied verbatim from the document text (character for character, including punctuation and units). Keep each quote short: the single line or phrase that proves the fact. Never paraphrase inside a quote.
- If a fact is absent, use null/false. Do not guess.
- H&P: 'is_completed_hp' is true only when THIS document is the H&P note itself (headings such as 'HISTORY AND PHYSICAL', 'H&P: PREOPERATIVE EVALUATION', 'HISTORY & PHYSICAL - PRE-OP', including annual wellness / establish-care H&Ps and documents whose title is misspelled). A pre-anesthesia or nursing note that says 'H&P reviewed' or 'H&P not on file' is NOT an H&P.
- Consent: the patient's signature must be documented as completed to be SIGNED. 'Patient signature: pending', a blank signature line, 'printed for review; not yet signed', or a portal request 'NOT COMPLETED' is PENDING_OR_UNSIGNED. Compare the procedure named on the consent with the planned procedure given to you (ignore wording differences such as 'Elective' or laterality; a different operation is a mismatch).
- Procedure date: DATE_STATED only when the text explicitly says when the planned procedure is scheduled or targeted (e.g. 'scheduled for 03/01/2026', 'Procedure date target: 2026-03-01', 'surgery on 03/01'). Dates of service, visit dates, signature/attestation dates, lab dates and last-dose dates are NOT procedure dates; if those are the only dates, use NOT_MENTIONED. 'date to be determined', 'pending OR availability' -> UNSCHEDULED_OR_TBD.
- Vitals: list every measured blood pressure and temperature in the text, including rechecks and addenda, each as its own reading with the clock time when the text gives one. Use the degree unit as written (C or F). Exclude 'See flowsheet', 'vitals deferred', and patient-reported home readings. Set vitals_deferred_or_not_recorded only when the text itself says vitals were deferred / not recorded / on a flowsheet, and quote that phrase; a note that simply has no vitals section gets false.
- Dates in output are YYYY-MM-DD; times are HH:MM."""

ANTICOAG_INSTRUCTIONS = """You are a careful medical-records reader. From ONE clinical document, extract facts about anticoagulant medication and any perioperative anticoagulation plan. You do not make decisions.

Rules:
- Anticoagulants: warfarin/Coumadin/Jantoven, apixaban/Eliquis, rivaroxaban/Xarelto, dabigatran/Pradaxa, edoxaban/Savaysa, betrixaban, enoxaparin/Lovenox, dalteparin/Fragmin, fondaparinux/Arixtra, heparin. Antiplatelets (aspirin/ASA, clopidogrel/Plavix, ticagrelor/Brilinta, prasugrel) are NOT anticoagulants; never list them.
- For each anticoagulant mentioned, report whether the PATIENT is currently taking it as of this note: 'maintained on', 'reports taking', 'taking as prescribed' -> CURRENTLY_TAKING. 'discontinued', 'stopped in 2020', 'switched from X to Y' (X -> NOT_CURRENTLY_TAKING, Y -> CURRENTLY_TAKING), 'not currently anticoagulated' -> NOT_CURRENTLY_TAKING. 'unable to confirm whether still taking' -> UNCERTAIN. A drug named only as a bridging agent or only inside hold/resume instructions -> OTHER.
- Plan: 'is_perioperative_plan' is true only when the document itself gives management recommendations for a NAMED anticoagulant around surgery (hold/stop/last dose/bridge/resume/restart, or an explicit statement that its management is deferred). Generic lines such as 'continue home medications except as directed by perioperative instructions', 'medications reviewed', or a medication list entry are NOT a plan: set is_perioperative_plan=false and leave the plan parts empty. pre_op covers stopping/holding/last dose/bridging before surgery; post_op covers resuming/restarting/bridging after surgery. 'explicit' requires a concrete action with timing. Phrases such as 'to be determined by the surgical team', 'will be addressed after surgery', 'recommendations to follow' are NOT explicit; set deferred_to_another_team and quote them.
- Quotes must be verbatim substrings of the document text; keep them short. Use null/false when absent."""


@dataclass
class DocExtraction:
    doc_id: str
    doc_type: str | None
    doc_date: str | None
    text: str
    facts: DocFacts | None = None
    anticoag: AnticoagFacts | None = None
    anticoag_attempted: bool = False
    errors: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)  # human-readable "field: quote" entries

    def verified(self, quote: str | None) -> bool:
        return quote_in_text(quote, self.text)


def _doc_user_text(doc: dict, planned_procedure: str | None) -> str:
    header = {
        "planned_procedure": planned_procedure,
        "document_type_label": doc.get("type"),
        "document_date": doc.get("date"),
        "author": doc.get("author"),
    }
    return "Context:\n" + json.dumps(header) + "\n\nDocument text:\n<<<\n" + (doc.get("text") or "") + "\n>>>"


def _collect_quotes_doc(f: DocFacts) -> list[tuple[str, str | None, bool]]:
    """(field, quote, required) triples; required means the claim is only valid with a quote."""
    q: list[tuple[str, str | None, bool]] = []
    q.append(("hp.quote", f.hp.quote, f.hp.is_completed_hp))
    q.append(("hp.references_hp_missing_quote", f.hp.references_hp_missing_quote, f.hp.references_hp_missing))
    q.append(("consent.quote", f.consent.quote, f.consent.patient_signed != "NOT_A_CONSENT"))
    q.append(("consent.references_consent_missing_quote", f.consent.references_consent_missing_quote, f.consent.references_consent_missing))
    q.append(("procedure_date.quote", f.procedure_date.quote, f.procedure_date.status != "NOT_MENTIONED"))
    for i, v in enumerate(f.vitals):
        q.append((f"vitals[{i}].quote", v.quote, True))
    q.append(("vitals_deferred_quote", f.vitals_deferred_quote, f.vitals_deferred_or_not_recorded))
    return q


def _collect_quotes_ac(f: AnticoagFacts) -> list[tuple[str, str | None, bool]]:
    q: list[tuple[str, str | None, bool]] = []
    for i, m in enumerate(f.mentions):
        q.append((f"mentions[{i}].quote", m.quote, True))
    q.append(("not_on_anticoagulant_quote", f.not_on_anticoagulant_quote, f.states_patient_not_on_anticoagulant))
    p = f.plan
    q.append(("plan.pre_op.quote", p.pre_op.quote, p.is_perioperative_plan and p.pre_op.present))
    q.append(("plan.post_op.quote", p.post_op.quote, p.is_perioperative_plan and p.post_op.present))
    q.append(("plan.deferral_quote", p.deferral_quote, p.deferred_to_another_team))
    return q


def _failed_quotes(text: str, triples) -> list[tuple[str, str | None]]:
    return [(name, quote) for name, quote, required in triples if required and not quote_in_text(quote, text)]


def _run_with_repair(llm: CachedLLM, *, instructions: str, user_text: str, schema_model, schema_name: str, text: str, collect):
    """Call the extractor; if quotes fail verification, retry once with the failures listed."""
    facts = llm.extract(instructions=instructions, user_text=user_text, schema_model=schema_model, schema_name=schema_name)
    failed = _failed_quotes(text, collect(facts))
    if failed:
        repair = (
            user_text
            + "\n\nYour previous answer contained quotes that are NOT verbatim substrings of the document. "
            "Re-extract, copying each quote exactly from the text (or drop the claim if it is not in the text):\n"
            + "\n".join(f"- {name}: {quote!r}" for name, quote in failed)
        )
        facts = llm.extract(instructions=instructions, user_text=repair, schema_model=schema_model, schema_name=schema_name)
        failed = _failed_quotes(text, collect(facts))
    return facts, failed


def extract_document(llm: CachedLLM, doc: dict, planned_procedure: str | None) -> DocExtraction:
    ex = DocExtraction(
        doc_id=str(doc.get("doc_id") or ""),
        doc_type=doc.get("type"),
        doc_date=doc.get("date"),
        text=doc.get("text") or "",
    )
    user_text = _doc_user_text(doc, planned_procedure)
    try:
        facts, failed = _run_with_repair(
            llm, instructions=DOC_FACTS_INSTRUCTIONS, user_text=user_text, schema_model=DocFacts,
            schema_name="doc_facts", text=ex.text, collect=_collect_quotes_doc,
        )
        ex.facts = facts
        ex.unverified += [f"doc_facts.{n}: {q!r}" for n, q in failed]
    except LLMError as exc:
        ex.errors.append(str(exc))

    if mentions_anticoagulation(ex.text):
        ex.anticoag_attempted = True
        try:
            ac, failed = _run_with_repair(
                llm, instructions=ANTICOAG_INSTRUCTIONS, user_text=user_text, schema_model=AnticoagFacts,
                schema_name="anticoag_facts", text=ex.text, collect=_collect_quotes_ac,
            )
            ex.anticoag = ac
            ex.unverified += [f"anticoag_facts.{n}: {q!r}" for n, q in failed]
        except LLMError as exc:
            ex.errors.append(str(exc))
    return ex


def extract_all(llm: CachedLLM, documents: list[dict], planned_procedure: str | None, max_workers: int = 6) -> list[DocExtraction]:
    """Extract every document; order is preserved. Failures are recorded, never raised."""
    if not documents:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(lambda d: extract_document(llm, d, planned_procedure), documents))
