"""Storage for document embeddings (used by semantic search).

Lives next to the other SQL code. It creates its own table on first use, so the
main schema does not have to change. One embedding per document.
"""

import json

from backend.app.db.database import connection

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS embeddings (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    vector_json TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _ensure_table(conn) -> None:
    conn.executescript(TABLE_SQL)


def save_embedding(document_id: int, vector: list[float]) -> None:
    with connection() as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (document_id, vector_json) VALUES (?, ?)",
            (document_id, json.dumps(vector)),
        )


def get_all_embeddings() -> list[tuple[int, list[float]]]:
    """Every stored (document_id, vector) pair."""
    with connection() as conn:
        _ensure_table(conn)
        rows = conn.execute("SELECT document_id, vector_json FROM embeddings").fetchall()
    return [(row["document_id"], json.loads(row["vector_json"])) for row in rows]


def documents_missing_embedding() -> list[tuple[int, str]]:
    """(document_id, text to embed) for extracted documents that have no embedding yet."""
    with connection() as conn:
        _ensure_table(conn)
        rows = conn.execute(
            """
            SELECT d.id, d.file_name, e.supplier_name, e.invoice_number, e.extracted_text
            FROM documents d
            JOIN extractions e ON e.document_id = d.id
            LEFT JOIN embeddings m ON m.document_id = d.id
            WHERE m.document_id IS NULL
            ORDER BY d.id
            """
        ).fetchall()
    result = []
    for row in rows:
        parts = [row["file_name"], row["supplier_name"], row["invoice_number"], row["extracted_text"]]
        result.append((row["id"], "\n".join(p for p in parts if p)))
    return result