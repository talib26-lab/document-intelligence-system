"""REST endpoints for uploading and managing documents.

Security notes:
- The user's file name is never used on disk. We store files under a random name.
- The real file type is checked from the file's bytes, not from its extension.
- Uploads are read in chunks and rejected when they pass the size limit.
- Heavy work (OCR, AI) runs in the background, so the API answers immediately.
"""

import os
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile

from backend.app.db import repository
from backend.app.db.database import PROJECT_ROOT
from backend.app.extraction.schemas import InvoiceData
from backend.app.processing.file_types import (
    CorruptedFileError,
    UnsupportedFileError,
    detect_file_kind,
)
from backend.app.services.job_runner import run_job
from backend.app.validation.validator import validate_invoice

router = APIRouter(tags=["documents"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB per file
MAX_FILES_PER_REQUEST = 20
CHUNK_SIZE = 1024 * 1024


class UploadRejected(Exception):
    """A file that must not be accepted (too big, empty, ...)."""


def get_upload_dir() -> Path:
    folder = Path(os.getenv("UPLOAD_DIR", PROJECT_ROOT / "data" / "uploads"))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


async def _save_upload(upload: UploadFile) -> tuple[Path, int]:
    """Stream an upload to disk under a random name. Returns (path, size)."""
    extension = Path(upload.filename or "").suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", extension):
        extension = ""
    path = get_upload_dir() / f"{secrets.token_hex(16)}{extension}"

    size = 0
    try:
        with open(path, "wb") as out:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise UploadRejected(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
                out.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path, size


# ---------- upload ----------

@router.post("/documents", status_code=202)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> dict:
    """Accept one or more files. Processing continues in the background."""
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(400, f"At most {MAX_FILES_PER_REQUEST} files per request.")

    accepted, rejected = [], []
    for upload in files:
        display_name = Path(upload.filename or "unnamed").name[:200] or "unnamed"
        path = None
        try:
            path, size = await _save_upload(upload)
            if size == 0:
                raise UploadRejected("The file is empty.")
            kind = detect_file_kind(path)  # checks the real bytes
        except UploadRejected as error:
            rejected.append({"file_name": display_name, "reason": str(error)})
            continue
        except (UnsupportedFileError, CorruptedFileError) as error:
            if path:
                path.unlink(missing_ok=True)
            rejected.append({"file_name": display_name, "reason": str(error)})
            continue

        document_id = repository.create_document(display_name, str(path), kind)
        background_tasks.add_task(run_job, document_id)
        accepted.append({"id": document_id, "file_name": display_name, "status": "queued"})

    if not accepted:
        raise HTTPException(400, detail={"message": "No file was accepted.", "rejected": rejected})
    return {"accepted": accepted, "rejected": rejected}


# ---------- reading ----------

@router.get("/documents")
def list_documents(
    status: str | None = Query(None, description="queued, processing, completed, needs_review or failed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    if status and status not in repository.STATUSES:
        raise HTTPException(400, f"Unknown status '{status}'.")
    return repository.list_documents(status=status, limit=limit, offset=offset)


@router.get("/documents/{document_id}")
def get_document(document_id: int) -> dict:
    document = repository.get_document(document_id)
    if document is None:
        raise HTTPException(404, "Document not found.")
    document["events"] = repository.get_events(document_id)
    return document


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    return repository.search_documents(q, limit=limit)


# ---------- manual correction ----------

@router.patch("/documents/{document_id}/correction")
def correct_document(document_id: int, corrected: InvoiceData) -> dict:
    """Store a human correction, then validate the corrected values again."""
    document = repository.get_document(document_id)
    if document is None:
        raise HTTPException(404, "Document not found.")
    if document["extraction"] is None:
        raise HTTPException(409, "This document has no extracted data to correct yet.")

    corrected.uncertain_fields = []  # a human has now confirmed the values
    repository.correct_extraction(document_id, corrected.model_dump())

    known = repository.known_invoices(exclude_document_id=document_id)
    result = validate_invoice(corrected, ocr_confidence=document["ocr_confidence"], known_invoices=known)
    repository.save_issues(document_id, [issue.model_dump() for issue in result.issues])

    status = "needs_review" if result.needs_review else "completed"
    repository.set_status(document_id, status, needs_review=result.needs_review)
    return repository.get_document(document_id)


# ---------- reprocess ----------

@router.post("/documents/{document_id}/reprocess", status_code=202)
def reprocess_document(document_id: int, background_tasks: BackgroundTasks) -> dict:
    document = repository.get_document(document_id)
    if document is None:
        raise HTTPException(404, "Document not found.")
    if document["status"] in ("queued", "processing"):
        raise HTTPException(409, "This document is already being processed.")

    repository.set_status(document_id, "queued")
    background_tasks.add_task(run_job, document_id)
    return {"id": document_id, "status": "queued"}