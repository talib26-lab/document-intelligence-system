"""Repository: every read/write of the database goes through these functions.

The rest of the app (API, background worker) never writes SQL. If we move to
PostgreSQL later, this is the only file that has to change.
"""

import json

from backend.app.db.database import connection

STATUSES = ("queued", "processing", "completed", "needs_review", "failed")


def _dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _add_event(conn, document_id: int, event: str, detail: str | None = None) -> None:
    conn.execute(
        "INSERT INTO processing_events (document_id, event, detail) VALUES (?, ?, ?)",
        (document_id, event, detail),
    )


# ---------- documents ----------

def create_document(file_name: str, stored_path: str, file_type: str | None = None) -> int:
    with connection() as conn:
        cursor = conn.execute(
            "INSERT INTO documents (file_name, stored_path, file_type) VALUES (?, ?, ?)",
            (file_name, stored_path, file_type),
        )
        document_id = cursor.lastrowid
        _add_event(conn, document_id, "uploaded", file_name)
        return document_id


def set_status(
    document_id: int,
    status: str,
    error_message: str | None = None,
    needs_review: bool | None = None,
) -> None:
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    with connection() as conn:
        conn.execute(
            """UPDATE documents
               SET status = ?, error_message = ?,
                   needs_review = COALESCE(?, needs_review),
                   updated_at = datetime('now')
               WHERE id = ?""",
            (status, error_message, None if needs_review is None else int(needs_review), document_id),
        )
        _add_event(conn, document_id, f"status:{status}", error_message)


def update_document_info(
    document_id: int,
    file_type: str | None,
    page_count: int | None,
    ocr_confidence: float | None,
) -> None:
    with connection() as conn:
        conn.execute(
            """UPDATE documents
               SET file_type = ?, page_count = ?, ocr_confidence = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (file_type, page_count, ocr_confidence, document_id),
        )


# ---------- extraction results ----------

def save_extraction(document_id: int, extracted_text: str, data: dict) -> None:
    """Save (or replace, when reprocessing) the AI result. Clears old corrections."""
    with connection() as conn:
        conn.execute(
            """INSERT INTO extractions
                   (document_id, extracted_text, data_json, invoice_number, supplier_name, invoice_date, total)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(document_id) DO UPDATE SET
                   extracted_text = excluded.extracted_text,
                   data_json = excluded.data_json,
                   corrected_json = NULL,
                   invoice_number = excluded.invoice_number,
                   supplier_name = excluded.supplier_name,
                   invoice_date = excluded.invoice_date,
                   total = excluded.total,
                   updated_at = datetime('now')""",
            (
                document_id,
                extracted_text,
                _dumps(data),
                data.get("invoice_number"),
                data.get("supplier_name"),
                data.get("invoice_date"),
                data.get("total"),
            ),
        )
        _add_event(conn, document_id, "extracted")


def save_issues(document_id: int, issues: list[dict]) -> None:
    """Replace the validation issues of a document with a fresh list."""
    with connection() as conn:
        conn.execute("DELETE FROM validation_issues WHERE document_id = ?", (document_id,))
        conn.executemany(
            """INSERT INTO validation_issues (document_id, field, code, severity, message)
               VALUES (?, ?, ?, ?, ?)""",
            [(document_id, i["field"], i["code"], i["severity"], i["message"]) for i in issues],
        )
        _add_event(conn, document_id, "validated", f"{len(issues)} issue(s)")


def correct_extraction(document_id: int, corrected: dict) -> bool:
    """Store a human correction. The original AI answer (data_json) is kept."""
    with connection() as conn:
        cursor = conn.execute(
            """UPDATE extractions
               SET corrected_json = ?, invoice_number = ?, supplier_name = ?,
                   invoice_date = ?, total = ?, updated_at = datetime('now')
               WHERE document_id = ?""",
            (
                _dumps(corrected),
                corrected.get("invoice_number"),
                corrected.get("supplier_name"),
                corrected.get("invoice_date"),
                corrected.get("total"),
                document_id,
            ),
        )
        if cursor.rowcount == 0:
            return False
        _add_event(conn, document_id, "corrected", "manual correction")
        return True


# ---------- reading ----------

def get_document(document_id: int) -> dict | None:
    with connection() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if doc is None:
            return None
        result = dict(doc)

        ext = conn.execute("SELECT * FROM extractions WHERE document_id = ?", (document_id,)).fetchone()
        if ext is None:
            result["extraction"] = None
        else:
            ai_data = json.loads(ext["data_json"])
            corrected = json.loads(ext["corrected_json"]) if ext["corrected_json"] else None
            result["extraction"] = {
                "ai_data": ai_data,
                "corrected_data": corrected,
                "final_data": corrected if corrected is not None else ai_data,
                "extracted_text": ext["extracted_text"],
            }

        issues = conn.execute(
            "SELECT field, code, severity, message FROM validation_issues WHERE document_id = ? ORDER BY id",
            (document_id,),
        ).fetchall()
        result["issues"] = [dict(i) for i in issues]
        return result


def list_documents(status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    query = "SELECT * FROM documents"
    params: list = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_events(document_id: int) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT event, detail, created_at FROM processing_events WHERE document_id = ? ORDER BY id",
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- duplicates ----------

def find_duplicate(supplier_name: str, invoice_number: str, exclude_document_id: int | None = None) -> int | None:
    """Return the id of another document with the same supplier + invoice number."""
    with connection() as conn:
        row = conn.execute(
            """SELECT document_id FROM extractions
               WHERE LOWER(TRIM(supplier_name)) = LOWER(TRIM(?))
                 AND LOWER(TRIM(invoice_number)) = LOWER(TRIM(?))
                 AND document_id != COALESCE(?, -1)
               LIMIT 1""",
            (supplier_name, invoice_number, exclude_document_id),
        ).fetchone()
        return row["document_id"] if row else None


def known_invoices(exclude_document_id: int | None = None) -> set[tuple[str, str]]:
    """All (supplier, invoice number) pairs already stored, for the validator."""
    with connection() as conn:
        rows = conn.execute(
            """SELECT supplier_name, invoice_number FROM extractions
               WHERE supplier_name IS NOT NULL AND invoice_number IS NOT NULL
                 AND document_id != COALESCE(?, -1)""",
            (exclude_document_id,),
        ).fetchall()
        return {(r["supplier_name"], r["invoice_number"]) for r in rows}


# ---------- search ----------

def search_documents(query: str, limit: int = 50) -> list[dict]:
    """Keyword search over file name, supplier, invoice number and document text."""
    escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    with connection() as conn:
        rows = conn.execute(
            """SELECT DISTINCT d.* FROM documents d
               LEFT JOIN extractions e ON e.document_id = d.id
               WHERE d.file_name LIKE ? ESCAPE '\\'
                  OR e.supplier_name LIKE ? ESCAPE '\\'
                  OR e.invoice_number LIKE ? ESCAPE '\\'
                  OR e.extracted_text LIKE ? ESCAPE '\\'
               ORDER BY d.id DESC LIMIT ?""",
            (pattern, pattern, pattern, pattern, limit),
        ).fetchall()
        return [dict(r) for r in rows]