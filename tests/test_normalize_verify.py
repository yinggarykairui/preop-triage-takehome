from datetime import date

import pytest

from preop_triage.normalize import (
    canonical_anticoagulant,
    canonical_lab,
    celsius_to_fahrenheit,
    is_antiplatelet,
    lab_status_counts,
    mentions_anticoagulation,
    parse_clock_time,
    parse_date,
    within_window,
)
from preop_triage.verify import quote_in_text


@pytest.mark.parametrize(
    "code,display,want",
    [
        ("CBC", "Complete Blood Count", "CBC"),
        ("LAB-CBC", "Complete Blood Count w/ Differential", "CBC"),
        ("CBC", "Hemogram/CBC", "CBC"),
        ("XYZ", "CBC w/ diff", "CBC"),
        ("CMP", "CMP (Comprehensive Metabolic Panel)", "CMP"),
        ("LAB-CMP", "Comprehensive Metabolic Panel w/ Magnesium", "CMP"),
        ("BMP", "Basic Metabolic Panel", "BMP"),
        ("LAB-BMP", "Basic Metabolic Panel w/ eGFR", "BMP"),
        ("TSH", "Thyroid Stimulating Hormone", None),
        ("HBA1C", "Hemoglobin A1c", None),
    ],
)
def test_canonical_lab(code, display, want):
    assert canonical_lab(code, display) == want


def test_lab_status():
    assert lab_status_counts("final") and lab_status_counts("Final")
    assert (
        not lab_status_counts("entered-in-error")
        and not lab_status_counts("preliminary")
        and not lab_status_counts(None)
    )


@pytest.mark.parametrize(
    "name,want",
    [
        ("warfarin (Coumadin) 5 mg PO daily", "warfarin"),
        ("Coumadin 5 mg PO daily", "warfarin"),
        ("Eliquis 5 mg PO BID", "apixaban"),
        ("Xarelto 20 mg PO daily with evening meal", "rivaroxaban"),
        ("dabigatran (Pradaxa) 150 mg PO BID", "dabigatran"),
        ("edoxaban (Savaysa) 60 mg PO daily", "edoxaban"),
        ("ASA 81 mg PO daily", None),
        ("clopidogrel 75 mg PO daily", None),
        ("lisinopril 20 mg", None),
    ],
)
def test_canonical_anticoagulant(name, want):
    assert canonical_anticoagulant(name) == want


def test_antiplatelet():
    assert is_antiplatelet("Aspirin EC 81 mg PO daily") and is_antiplatelet("ASA 81") and is_antiplatelet("Plavix")
    assert not is_antiplatelet("apixaban 5 mg")


def test_mentions_prefilter():
    assert mentions_anticoagulation("Patient also reports taking Eliquis 5 mg")
    assert mentions_anticoagulation("not on any blood thinners")
    assert not mentions_anticoagulation("Routine follow-up. No medication changes today.")


def test_units_and_dates():
    assert (
        celsius_to_fahrenheit(37.9) == 100.22
        and celsius_to_fahrenheit(38.6) == 101.48
        and celsius_to_fahrenheit(38.0) == 100.4
    )
    assert parse_date("2026-02-17T09:05:00Z") == date(2026, 2, 17) and parse_date("02/27/2026") == date(2026, 2, 27)
    assert parse_date(None) is None and parse_date("TBD") is None
    assert parse_clock_time("08:30").hour == 8 and parse_clock_time("x") is None
    assert within_window(date(2026, 3, 31), date(2026, 3, 1), 30) and not within_window(
        date(2026, 3, 31), date(2026, 2, 28), 30
    )
    assert not within_window(date(2026, 3, 31), date(2026, 4, 1), 30)


def test_quote_verifier():
    text = "VITAL SIGNS:\n  08:06  NIBP 189/112, T 37.1 C, HR 74.\nADDENDUM 08:30: Re-measured 137/78 mmHg"
    assert quote_in_text("NIBP 189/112, T 37.1 C", text)
    assert quote_in_text("08:06 NIBP 189/112", text)  # whitespace-normalized
    assert quote_in_text("ADDENDUM 08:30: Re-measured 137/78 mmHg", text)
    assert not quote_in_text("Re-measured 137/79 mmHg", text)  # altered number
    assert not quote_in_text("", text) and not quote_in_text(None, text) and not quote_in_text("x", None)
    assert not quote_in_text("No vitals recorded in the note", text)  # paraphrase/hallucination


def test_quote_verifier_tolerates_encoding_noise_but_not_numbers():
    text = "08:44  BP 127/80, Temperature 36.6 \u00b0C (oral)\nPlanned procedure: lumbar laminectomy (date to be determined pending OR availability)"
    assert quote_in_text("08:44 BP 127/80, Temperature 36.6 \x176C (oral)", text)  # garbled degree sign
    assert quote_in_text("Temperature 36.6 C", text)
    assert quote_in_text(
        "Temp 98.8 \x176F", "Vitals 10:05  Temp 98.8 \u00b0F temporal"
    )  # model mojibake for the degree sign
    assert not quote_in_text("Temp 98.9 \x176F", "Vitals 10:05  Temp 98.8 \u00b0F temporal")
    assert quote_in_text(
        "lumbar laminectomy date to be determined pending OR availability", text
    )  # dropped parentheses
    assert not quote_in_text("Temperature 36.8 C", text)
    assert not quote_in_text("BP 127/90", text)
