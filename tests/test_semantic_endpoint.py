"""Tests for GET /search/semantic using a fake embedder (no Gemini calls)."""

import pytest
from fastapi.testclient import TestClient

from backend.app.db import database, embedding_repository, repository
from backend.app.services import semantic


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    database.init_db()

    def add_doc(name, text):
        doc_id = repository.create_document(name, str(tmp_path / name), None)
        with database.connection() as conn:
            conn.execute(
                "INSERT INTO extractions (document_id, extracted_text, data_json) VALUES (?, ?, ?)",
                (doc_id, text, "{}"),
            )
        return doc_id

    # Hand-made 2D "meaning" space: x = fuel/transport, y = office supplies
    vectors = {"petrol diesel fuel": [1.0, 0.0], "paper pens stationery": [0.0, 1.0]}
    calls = []

    def fake_embed(texts):
        calls.append(list(texts))
        out = []
        for t in texts:
            if "petrol" in t or "fuel" in t or "vehicle" in t:
                out.append([1.0, 0.0])
            else:
                out.append([0.0, 1.0])
        return out

    monkeypatch.setattr(semantic, "embed_texts", fake_embed)

    from backend.app.main import app

    c = TestClient(app)
    c.doc_fuel = add_doc("fuel.pdf", "petrol diesel fuel")
    c.doc_paper = add_doc("paper.pdf", "paper pens stationery")
    c.calls = calls
    return c


def test_semantic_search_ranks_by_meaning(client):
    response = client.get("/search/semantic", params={"q": "vehicle"})
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["document_id"] == client.doc_fuel
    assert results[0]["score"] > 0.9


def test_embeddings_are_stored_and_reused(client):
    client.get("/search/semantic", params={"q": "vehicle"})
    assert len(embedding_repository.get_all_embeddings()) == 2
    client.calls.clear()
    client.get("/search/semantic", params={"q": "vehicle"})
    # second search embeds only the query, not the documents again
    assert client.calls == [["vehicle"]]


def test_semantic_search_requires_query(client):
    assert client.get("/search/semantic").status_code == 422