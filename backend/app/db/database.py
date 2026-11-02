"""SQLite database layer.

All SQL lives in the db package, so the rest of the app never talks to the
database directly. To move to PostgreSQL later, only this layer has to change.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Project root = three levels above this file (backend/app/db/database.py)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "documents.db"

# Document statuses: queued -> processing -> completed | needs_review | failed

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name       TEXT NOT NULL,
    stored_path     TEXT NOT NULL,
    file_type       TEXT,
    status          TEXT NOT NULL DEFAULT 'queued',
    error_message   TEXT,
    page_count      INTEGER,
    ocr_confidence  REAL,
    needs_review    INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extractions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    extracted_text  TEXT,
    data_json       TEXT NOT NULL,   -- what the AI returned (never overwritten)
    corrected_json  TEXT,            -- human corrections (null until corrected)
    invoice_number  TEXT,
    supplier_name   TEXT,
    invoice_date    TEXT,
    total           REAL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS validation_issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    field       TEXT,
    code        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    message     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processing_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_extractions_invoice ON extractions(supplier_name, invoice_number);
CREATE INDEX IF NOT EXISTS idx_issues_document ON validation_issues(document_id);
CREATE INDEX IF NOT EXISTS idx_events_document ON processing_events(document_id);
"""


def get_db_path() -> Path:
    """Database file location. Can be changed with the DATABASE_PATH env variable."""
    return Path(os.getenv("DATABASE_PATH", DEFAULT_DB_PATH))


def get_connection() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # readers do not block the writer
    return conn


@contextmanager
def connection():
    """Open a connection, commit on success, roll back on error, always close."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they do not exist yet. Safe to run many times."""
    with connection() as conn:
        conn.executescript(SCHEMA)