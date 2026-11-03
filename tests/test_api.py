"""API tests. They use a fake AI, a temporary database and a temporary upload folder."""

import pytest
from fastapi.testclient import TestClient

from backend.app.api import documents as documents_api
from backend.app.db import repository
from backend.app.extraction.schemas import InvoiceData
from backend.app.main import app
from backend.app.services import job_runner

CSV_BYTES = b"Invoice,00427\nSupplier,Sunrise Trading\nTotal,14500\n"


def fake_extractor(text: str) -> InvoiceData:
    return InvoiceData(
        invoice_number="00427",
        invoice_date="2026-10-15",
        supplier_name="Sunrise Trading",
        subtotal=14500.0,
        total=14500.0,
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    # Make the background job use the fake AI instead of calling Gemini.
    monkeypatch.setattr(
        documents_api, "run_job", lambda document_id: job_runner.run_job(document_id, extractor=fake_extractor)
    )
    with TestClient(app) as test_client:  # startup creates the tables
        yield test_client


def _upload(client, name="invoice.csv", content=CSV_BYTES, content_type="text/csv"):
    return client.post("/documents", files=[("files", (name, content, content_type))])


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_upload_is_accepted_and_processed_in_background(client):
    response = _upload(client)
    assert response.status_code == 202
    body = response.json()
    assert body["rejected"] == []
    document_id = body["accepted"][0]["id"]

    doc = client.get(f"/documents/{document_id}").json()
    assert doc["status"] == "completed"
    assert doc["extraction"]["final_data"]["invoice_number"] == "00427"
    assert [e["event"] for e in doc["events"]][0] == "uploaded"


def test_fake_extension_is_rejected(client):
    fake_pdf = b"MZ\x90\x00 this is really an executable, not a pdf"
    response = _upload(client, name="invoice.pdf", content=fake_pdf, content_type="application/pdf")
    assert response.status_code == 400
    assert len(response.json()["detail"]["rejected"]) == 1


def test_empty_file_is_rejected(client):
    response = _upload(client, content=b"")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]["rejected"][0]["reason"].lower()


def test_oversized_file_is_rejected_and_not_kept_on_disk(client, tmp_path, monkeypatch):
    monkeypatch.setattr(documents_api, "MAX_UPLOAD_BYTES", 100)
    response = _upload(client, content=b"a,b\n" * 100)
    assert response.status_code == 400
    assert "larger" in response.json()["detail"]["rejected"][0]["reason"].lower()
    assert list((tmp_path / "uploads").iterdir()) == []  # nothing left behind


def test_path_traversal_file_name_is_harmless(client, tmp_path):
    response = _upload(client, name="../../evil.csv")
    assert response.status_code == 202
    stored = [p.name for p in (tmp_path / "uploads").iterdir()]
    assert len(stored) == 1
    assert "evil" not in stored[0]  # our own random name is used on disk
    assert not (tmp_path.parent / "evil.csv").exists()


def test_good_and_bad_files_in_one_request(client):
    response = client.post(
        "/documents",
        files=[
            ("files", ("good.csv", CSV_BYTES, "text/csv")),
            ("files", ("bad.pdf", b"not a real pdf at all", "application/pdf")),
        ],
    )
    assert response.status_code == 202
    body = response.json()
    assert len(body["accepted"]) == 1
    assert len(body["rejected"]) == 1


def test_unknown_document_returns_404(client):
    assert client.get("/documents/9999").status_code == 404
    assert client.post("/documents/9999/reprocess").status_code == 404
    assert client.patch("/documents/9999/correction", json={"total": 1}).status_code == 404


def test_correction_keeps_ai_answer_and_revalidates(client):
    document_id = _upload(client).json()["accepted"][0]["id"]

    corrected = {
        "invoice_number": "00427",
        "invoice_date": "2026-10-15",
        "supplier_name": "Sunrise Trading Ltd",
        "subtotal": 14500.0,
        "total": 14500.0,
    }
    response = client.patch(f"/documents/{document_id}/correction", json=corrected)
    assert response.status_code == 200
    extraction = response.json()["extraction"]
    assert extraction["ai_data"]["supplier_name"] == "Sunrise Trading"  # original kept
    assert extraction["final_data"]["supplier_name"] == "Sunrise Trading Ltd"  # human wins
    assert response.json()["status"] == "completed"

    # a wrong total is caught again after a correction
    corrected["total"] = 99999.0
    response = client.patch(f"/documents/{document_id}/correction", json=corrected)
    assert response.json()["status"] == "needs_review"
    assert "total_mismatch" in [i["code"] for i in response.json()["issues"]]


def test_reprocess_and_status_filter(client):
    document_id = _upload(client).json()["accepted"][0]["id"]
    assert client.post(f"/documents/{document_id}/reprocess").status_code == 202
    assert client.get(f"/documents/{document_id}").json()["status"] == "completed"

    assert client.get("/documents", params={"status": "completed"}).json()[0]["id"] == document_id
    assert client.get("/documents", params={"status": "failed"}).json() == []
    assert client.get("/documents", params={"status": "banana"}).status_code == 400


def test_search(client):
    document_id = _upload(client).json()["accepted"][0]["id"]
    results = client.get("/search", params={"q": "sunrise"}).json()
    assert [r["id"] for r in results] == [document_id]
    assert client.get("/search", params={"q": "nothing-matches"}).json() == []
    assert client.get("/search", params={"q": ""}).status_code == 422  # empty query is invalid