"""Rule-based checks that run AFTER the AI extraction.

We never trust the AI blindly. These rules re-check the numbers and flag
anything suspicious so a human can review it before it is used.
"""

from datetime import date

from pydantic import BaseModel

from backend.app.extraction.schemas import InvoiceData

TOLERANCE = 0.01  # allowed rounding difference in money amounts
LOW_OCR_CONFIDENCE = 60.0  # below this OCR score, a human should look
REQUIRED_FIELDS = ["invoice_number", "invoice_date", "supplier_name", "total"]


class Issue(BaseModel):
    field: str
    code: str
    severity: str  # "error" or "warning"
    message: str


class ValidationResult(BaseModel):
    issues: list[Issue] = []
    needs_review: bool = False


def _differs(a: float, b: float) -> bool:
    return abs(a - b) > TOLERANCE


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_invoice(
    data: InvoiceData,
    ocr_confidence: float | None = None,
    known_invoices: set[tuple[str, str]] | None = None,
) -> ValidationResult:
    """Check extracted invoice data and return every problem found.

    known_invoices: set of (supplier_name, invoice_number) already stored,
    used to detect duplicates.
    """
    issues: list[Issue] = []

    def add(field: str, code: str, severity: str, message: str) -> None:
        issues.append(Issue(field=field, code=code, severity=severity, message=message))

    # 1. Required fields
    for name in REQUIRED_FIELDS:
        if getattr(data, name) in (None, ""):
            add(name, "missing_field", "error", f"Required field '{name}' is missing.")

    # 2. Dates
    invoice_date = None
    due_date = None
    if data.invoice_date:
        invoice_date = _parse_date(data.invoice_date)
        if invoice_date is None:
            add("invoice_date", "invalid_date", "error", f"'{data.invoice_date}' is not a valid date.")
    if data.due_date:
        due_date = _parse_date(data.due_date)
        if due_date is None:
            add("due_date", "invalid_date", "error", f"'{data.due_date}' is not a valid date.")
    if invoice_date and due_date and due_date < invoice_date:
        add("due_date", "due_before_issue", "warning", "Due date is earlier than the invoice date.")

    # 3. Currency
    if data.currency and len(data.currency) != 3:
        add("currency", "invalid_currency", "warning", f"'{data.currency}' is not a 3-letter currency code.")

    # 4. Negative amounts
    for name in ["subtotal", "tax", "total"]:
        value = getattr(data, name)
        if value is not None and value < 0:
            add(name, "negative_amount", "error", f"'{name}' is negative ({value}).")

    # 5. Line items: quantity x unit price = amount
    amounts = []
    for index, item in enumerate(data.line_items, start=1):
        label = f"line_items[{index}]"
        if item.quantity is not None and item.unit_price is not None and item.amount is not None:
            expected = item.quantity * item.unit_price
            if _differs(expected, item.amount):
                add(label, "line_total_mismatch", "error",
                    f"Quantity x unit price = {expected:.2f}, but amount is {item.amount:.2f}.")
        if item.amount is not None:
            amounts.append(item.amount)

    # 6. Sum of line items = subtotal
    if data.subtotal is not None and data.line_items and len(amounts) == len(data.line_items):
        line_sum = sum(amounts)
        if _differs(line_sum, data.subtotal):
            add("subtotal", "subtotal_mismatch", "error",
                f"Line items add up to {line_sum:.2f}, but subtotal is {data.subtotal:.2f}.")

    # 7. Subtotal + tax = total
    if data.subtotal is not None and data.total is not None:
        expected_total = data.subtotal + (data.tax or 0)
        if _differs(expected_total, data.total):
            hint = " (tax is missing)" if data.tax is None else ""
            add("total", "total_mismatch", "error",
                f"Subtotal + tax = {expected_total:.2f}, but total is {data.total:.2f}{hint}.")

    # 8. Fields the AI itself was unsure about
    for name in data.uncertain_fields:
        add(name, "uncertain_field", "warning", f"The AI was not sure about '{name}'.")

    # 9. Poor scan quality
    if ocr_confidence is not None and ocr_confidence < LOW_OCR_CONFIDENCE:
        add("document", "low_ocr_confidence", "warning",
            f"OCR confidence is low ({ocr_confidence:.0f}%). Text may be misread.")

    # 10. Duplicate invoice
    if known_invoices and data.supplier_name and data.invoice_number:
        if (data.supplier_name, data.invoice_number) in known_invoices:
            add("invoice_number", "duplicate_invoice", "error",
                f"Invoice {data.invoice_number} from {data.supplier_name} already exists.")

    return ValidationResult(issues=issues, needs_review=len(issues) > 0)