"""Tests for the database repository.

Every test runs against a throw-away database in a temp folder, so the real
data/documents.db is never touched.
"""

import pytest

from backend.app.db import repository
from backend.app.db.database import init_db


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


def _new_doc(name="invoice.pdf"):
    return repository.create_document(name, f"data/uploads/{name}", "pdf")


def _extract(document_id, **fields):
    data = {"invoice_number": "00427", "supplier_name": "Sunrise Trading", "total": 14500.0}
    data.update(fields)
    repository.save_extraction(document_id, "some document text", data)


def test_create_and_get_document():
    document_id = _new_doc()
    doc = repository.get_document(document_id)
    assert doc["file_name"] == "invoice.pdf"
    assert doc["status"] == "queued"
    assert doc["extraction"] is None
    assert doc["issues"] == []


def test_missing_document_returns_none():
    assert repository.get_document(9999) is None


def test_status_change_and_invalid_status():
    document_id = _new_doc()
    repository.set_status(document_id, "processing")
    assert repository.get_document(document_id)["status"] == "processing"

    repository.set_status(document_id, "failed", error_message="corrupt file")
    doc = repository.get_document(document_id)
    assert doc["status"] == "failed"
    assert doc["error_message"] == "corrupt file"

    with pytest.raises(ValueError):
        repository.set_status(document_id, "banana")


def test_save_extraction_and_final_data():
    document_id = _new_doc()
    _extract(document_id)
    extraction = repository.get_document(document_id)["extraction"]
    assert extraction["ai_data"]["invoice_number"] == "00427"
    assert extraction["corrected_data"] is None
    assert extraction["final_data"] == extraction["ai_data"]


def test_correction_keeps_original_ai_answer():
    document_id = _new_doc()
    _extract(document_id, total=15200.0)

    corrected = {"invoice_number": "00427", "supplier_name": "Sunrise Trading", "total": 15000.0}
    assert repository.correct_extraction(document_id, corrected) is True

    extraction = repository.get_document(document_id)["extraction"]
    assert extraction["ai_data"]["total"] == 15200.0  # original AI answer untouched
    assert extraction["final_data"]["total"] == 15000.0  # human value wins


def test_correcting_a_document_without_extraction_returns_false():
    document_id = _new_doc()
    assert repository.correct_extraction(document_id, {"total": 1}) is False


def test_reprocessing_clears_old_correction():
    document_id = _new_doc()
    _extract(document_id)
    repository.correct_extraction(document_id, {"invoice_number": "X", "supplier_name": "Y", "total": 1.0})

    _extract(document_id, total=99.0)  # reprocess: new AI result

    extraction = repository.get_document(document_id)["extraction"]
    assert extraction["corrected_data"] is None
    assert extraction["final_data"]["total"] == 99.0


def test_duplicate_detection_ignores_case_and_spaces():
    first = _new_doc("a.pdf")
    second = _new_doc("b.pdf")
    _extract(first)

    found = repository.find_duplicate("  SUNRISE trading ", " 00427 ", exclude_document_id=second)
    assert found == first
    # a document is never a duplicate of itself
    assert repository.find_duplicate("Sunrise Trading", "00427", exclude_document_id=first) is None
    assert repository.find_duplicate("Sunrise Trading", "99999") is None


def test_known_invoices():
    first = _new_doc("a.pdf")
    _extract(first)
    assert repository.known_invoices() == {("Sunrise Trading", "00427")}
    assert repository.known_invoices(exclude_document_id=first) == set()


def test_search():
    document_id = _new_doc("march_invoice.pdf")
    _extract(document_id)

    assert [d["id"] for d in repository.search_documents("sunrise")] == [document_id]  # supplier
    assert [d["id"] for d in repository.search_documents("00427")] == [document_id]  # invoice number
    assert [d["id"] for d in repository.search_documents("march")] == [document_id]  # file name
    assert [d["id"] for d in repository.search_documents("document text")] == [document_id]  # body text
    assert repository.search_documents("nothing-matches-this") == []
    assert repository.search_documents("%") == []  # wildcard characters are not special


def test_save_issues_replaces_old_ones():
    document_id = _new_doc()
    issue = {"field": "total", "code": "total_mismatch", "severity": "error", "message": "bad total"}
    repository.save_issues(document_id, [issue, issue])
    assert len(repository.get_document(document_id)["issues"]) == 2

    repository.save_issues(document_id, [issue])
    assert len(repository.get_document(document_id)["issues"]) == 1


def test_audit_trail_records_events_in_order():
    document_id = _new_doc()
    repository.set_status(document_id, "processing")
    _extract(document_id)
    repository.save_issues(document_id, [])
    repository.correct_extraction(document_id, {"invoice_number": "1", "supplier_name": "S", "total": 1.0})

    events = [e["event"] for e in repository.get_events(document_id)]
    assert events == ["uploaded", "status:processing", "extracted", "validated", "corrected"]


def test_list_documents_filters_by_status():
    first = _new_doc("a.pdf")
    second = _new_doc("b.pdf")
    repository.set_status(second, "failed", error_message="x")

    assert [d["id"] for d in repository.list_documents(status="failed")] == [second]
    assert {d["id"] for d in repository.list_documents()} == {first, second}