"""Tests for the job runner, using a fake AI so no network or API key is needed."""

import pytest

from backend.app.db import repository
from backend.app.db.database import init_db
from backend.app.extraction.invoice_extractor import ExtractionError
from backend.app.extraction.schemas import InvoiceData
from backend.app.services.job_runner import run_job

CSV_TEXT = "Invoice,00427\nSupplier,Sunrise Trading\nTotal,14500\n"


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


def _upload(tmp_path, name="invoice.csv", content=CSV_TEXT) -> int:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return repository.create_document(name, str(path))


def good_extractor(text: str) -> InvoiceData:
    return InvoiceData(
        invoice_number="00427",
        invoice_date="2026-10-15",
        supplier_name="Sunrise Trading",
        subtotal=14500.0,
        total=14500.0,
    )


def wrong_total_extractor(text: str) -> InvoiceData:
    data = good_extractor(text)
    data.total = 15000.0  # does not match the subtotal
    return data


def failing_extractor(text: str) -> InvoiceData:
    raise ExtractionError("AI is down")


def crashing_extractor(text: str) -> InvoiceData:
    raise RuntimeError("boom")


def test_successful_document_is_completed(tmp_path):
    document_id = _upload(tmp_path)
    run_job(document_id, extractor=good_extractor)

    doc = repository.get_document(document_id)
    assert doc["status"] == "completed"
    assert doc["needs_review"] == 0
    assert doc["issues"] == []
    assert doc["extraction"]["final_data"]["invoice_number"] == "00427"
    assert doc["file_type"] == "csv"


def test_wrong_numbers_send_document_to_review(tmp_path):
    document_id = _upload(tmp_path)
    run_job(document_id, extractor=wrong_total_extractor)

    doc = repository.get_document(document_id)
    assert doc["status"] == "needs_review"
    assert doc["needs_review"] == 1
    assert "total_mismatch" in [i["code"] for i in doc["issues"]]


def test_ai_failure_marks_document_failed(tmp_path):
    document_id = _upload(tmp_path)
    run_job(document_id, extractor=failing_extractor)

    doc = repository.get_document(document_id)
    assert doc["status"] == "failed"
    assert "AI is down" in doc["error_message"]


def test_unexpected_error_never_crashes_the_worker(tmp_path):
    document_id = _upload(tmp_path)
    run_job(document_id, extractor=crashing_extractor)  # must not raise

    doc = repository.get_document(document_id)
    assert doc["status"] == "failed"
    assert "Unexpected error: boom" in doc["error_message"]


def test_unsupported_file_type_fails(tmp_path):
    document_id = _upload(tmp_path, name="notes.txt", content="hello")
    run_job(document_id, extractor=good_extractor)
    assert repository.get_document(document_id)["status"] == "failed"


def test_missing_file_fails(tmp_path):
    document_id = repository.create_document("ghost.csv", str(tmp_path / "ghost.csv"))
    run_job(document_id, extractor=good_extractor)
    assert repository.get_document(document_id)["status"] == "failed"


def test_unknown_document_id_is_ignored():
    run_job(9999, extractor=good_extractor)  # must not raise


def test_duplicate_invoice_is_flagged(tmp_path):
    first = _upload(tmp_path, name="a.csv")
    second = _upload(tmp_path, name="b.csv")

    run_job(first, extractor=good_extractor)
    run_job(second, extractor=good_extractor)

    assert repository.get_document(first)["status"] == "completed"
    doc = repository.get_document(second)
    assert doc["status"] == "needs_review"
    assert "duplicate_invoice" in [i["code"] for i in doc["issues"]]


def test_failed_document_can_be_reprocessed(tmp_path):
    document_id = _upload(tmp_path)
    run_job(document_id, extractor=failing_extractor)
    assert repository.get_document(document_id)["status"] == "failed"

    run_job(document_id, extractor=good_extractor)  # reprocess

    doc = repository.get_document(document_id)
    assert doc["status"] == "completed"
    assert doc["extraction"] is not None
    events = [e["event"] for e in repository.get_events(document_id)]
    assert events.count("status:processing") == 2
    assert "status:failed" in events