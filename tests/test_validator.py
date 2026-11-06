"""Unit tests for the rule-based validator. No AI and no network are needed.

Strategy: start from one fully correct invoice, then break exactly ONE thing per
test and check that exactly the expected issue is reported.
"""

import pytest

from backend.app.extraction.schemas import InvoiceData
from backend.app.validation.validator import validate_invoice


def make(**overrides) -> InvoiceData:
    """A fully correct invoice. Tests override single fields to break it."""
    data = {
        "invoice_number": "INV-100",
        "invoice_date": "2026-03-01",
        "due_date": "2026-03-31",
        "supplier_name": "Acme Ltd",
        "customer_name": "Delta Co",
        "currency": "USD",
        "subtotal": 125.0,
        "tax": 6.25,
        "total": 131.25,
        "line_items": [
            {"description": "Chair", "quantity": 2, "unit_price": 50.0, "amount": 100.0},
            {"description": "Lamp", "quantity": 1, "unit_price": 25.0, "amount": 25.0},
        ],
        "uncertain_fields": [],
    }
    data.update(overrides)
    return InvoiceData(**data)


def codes(result) -> list:
    return [issue.code for issue in result.issues]


def test_clean_invoice_has_no_issues():
    result = validate_invoice(make())
    assert result.issues == []
    assert result.needs_review is False


@pytest.mark.parametrize("field", ["invoice_number", "invoice_date", "supplier_name", "total"])
def test_missing_required_field_is_an_error(field):
    result = validate_invoice(make(**{field: None}))
    issues = [i for i in result.issues if i.code == "missing_field"]
    assert [i.field for i in issues] == [field]
    assert issues[0].severity == "error"
    assert result.needs_review is True


def test_empty_string_counts_as_missing():
    result = validate_invoice(make(invoice_number=""))
    assert "missing_field" in codes(result)


def test_invalid_invoice_date():
    result = validate_invoice(make(invoice_date="31/02/2026"))
    assert "invalid_date" in codes(result)


def test_invalid_due_date():
    result = validate_invoice(make(due_date="not a date"))
    assert "invalid_date" in codes(result)


def test_due_date_before_invoice_date_is_a_warning():
    result = validate_invoice(make(invoice_date="2026-03-10", due_date="2026-03-01"))
    issue = next(i for i in result.issues if i.code == "due_before_issue")
    assert issue.severity == "warning"
    assert result.needs_review is True


def test_missing_due_date_is_fine():
    result = validate_invoice(make(due_date=None))
    assert result.issues == []


@pytest.mark.parametrize("currency", ["US", "DOLLAR"])
def test_bad_currency_code(currency):
    assert "invalid_currency" in codes(validate_invoice(make(currency=currency)))


def test_missing_currency_is_fine():
    assert validate_invoice(make(currency=None)).issues == []


def test_negative_amount():
    # total made consistent with the negative subtotal so only one rule fires
    result = validate_invoice(make(subtotal=-125.0, tax=0.0, total=-125.0,
                                   line_items=[]))
    assert "negative_amount" in codes(result)


def test_line_total_mismatch_names_the_line():
    items = [
        {"description": "Chair", "quantity": 2, "unit_price": 50.0, "amount": 150.0},
        {"description": "Lamp", "quantity": 1, "unit_price": 25.0, "amount": 25.0},
    ]
    result = validate_invoice(make(line_items=items, subtotal=175.0, tax=0.0, total=175.0))
    issue = next(i for i in result.issues if i.code == "line_total_mismatch")
    assert issue.field == "line_items[1]"


def test_tiny_rounding_difference_is_tolerated():
    items = [{"description": "Pen", "quantity": 3, "unit_price": 10.0, "amount": 30.005}]
    result = validate_invoice(make(line_items=items, subtotal=30.005, tax=0.0, total=30.005))
    assert "line_total_mismatch" not in codes(result)


def test_line_with_missing_price_is_skipped_not_flagged():
    items = [{"description": "Pen", "quantity": 3, "unit_price": None, "amount": 30.0}]
    result = validate_invoice(make(line_items=items, subtotal=30.0, tax=0.0, total=30.0))
    assert "line_total_mismatch" not in codes(result)


def test_subtotal_mismatch():
    result = validate_invoice(make(subtotal=200.0, tax=0.0, total=200.0))
    assert "subtotal_mismatch" in codes(result)


def test_subtotal_check_skipped_when_a_line_amount_is_missing():
    items = [
        {"description": "Chair", "quantity": 2, "unit_price": 50.0, "amount": 100.0},
        {"description": "Lamp", "quantity": None, "unit_price": None, "amount": None},
    ]
    result = validate_invoice(make(line_items=items))
    assert "subtotal_mismatch" not in codes(result)


def test_total_mismatch():
    result = validate_invoice(make(total=999.0))
    issue = next(i for i in result.issues if i.code == "total_mismatch")
    assert issue.severity == "error"


def test_missing_tax_with_total_equal_to_subtotal_is_fine():
    result = validate_invoice(make(tax=None, total=125.0))
    assert result.issues == []


def test_missing_tax_mismatch_mentions_the_hint():
    result = validate_invoice(make(tax=None, total=131.25))
    issue = next(i for i in result.issues if i.code == "total_mismatch")
    assert "tax is missing" in issue.message


def test_uncertain_fields_become_warnings():
    result = validate_invoice(make(uncertain_fields=["invoice_date", "total"]))
    warnings = [i for i in result.issues if i.code == "uncertain_field"]
    assert sorted(i.field for i in warnings) == ["invoice_date", "total"]
    assert all(i.severity == "warning" for i in warnings)
    assert result.needs_review is True  # a warning alone is enough for review


@pytest.mark.parametrize("confidence, flagged", [(59.9, True), (60.0, False), (95.0, False), (None, False)])
def test_low_ocr_confidence_threshold(confidence, flagged):
    result = validate_invoice(make(), ocr_confidence=confidence)
    assert ("low_ocr_confidence" in codes(result)) is flagged


def test_duplicate_invoice_detected():
    known = {("Acme Ltd", "INV-100")}
    result = validate_invoice(make(), known_invoices=known)
    assert "duplicate_invoice" in codes(result)


def test_same_number_from_another_supplier_is_not_a_duplicate():
    known = {("Other Ltd", "INV-100")}
    assert "duplicate_invoice" not in codes(validate_invoice(make(), known_invoices=known))


def test_no_known_invoices_means_no_duplicate_check():
    assert "duplicate_invoice" not in codes(validate_invoice(make(), known_invoices=None))


def test_several_problems_are_all_reported():
    result = validate_invoice(make(invoice_number=None, total=999.0, currency="X"))
    assert {"missing_field", "total_mismatch", "invalid_currency"} <= set(codes(result))