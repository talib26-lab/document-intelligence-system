"""The job runner: processes one uploaded document from start to finish.

Steps: read the file (OCR if needed) -> AI extraction -> validation -> save.
Any failure marks the document as 'failed' with a reason, so one bad file can
never crash the system, and a failed document can simply be run again.
"""

import logging

from backend.app.db import repository
from backend.app.extraction.invoice_extractor import (
    ExtractionError,
    build_document_text,
    extract_invoice,
)
from backend.app.processing.file_types import CorruptedFileError, UnsupportedFileError
from backend.app.processing.pipeline import process_document
from backend.app.validation.validator import validate_invoice

logger = logging.getLogger(__name__)


def _average_confidence(processed: dict) -> float | None:
    """Average OCR confidence over the pages that were read by OCR."""
    scores = [p["confidence"] for p in processed.get("pages", []) if p.get("confidence") is not None]
    return sum(scores) / len(scores) if scores else None


def run_job(document_id: int, extractor=extract_invoice) -> None:
    """Process one document. Never raises: every failure is stored on the document.

    extractor: the function that calls the AI. Tests pass a fake one so they
    do not need the network or an API key.
    """
    document = repository.get_document(document_id)
    if document is None:
        logger.warning("Job for unknown document %s ignored", document_id)
        return

    try:
        repository.set_status(document_id, "processing")

        processed = process_document(document["stored_path"])
        confidence = _average_confidence(processed)
        repository.update_document_info(
            document_id,
            file_type=processed.get("file_type"),
            page_count=processed.get("page_count"),
            ocr_confidence=confidence,
        )

        text = build_document_text(processed)
        invoice = extractor(text)

        known = repository.known_invoices(exclude_document_id=document_id)
        repository.save_extraction(document_id, text, invoice.model_dump())

        result = validate_invoice(invoice, ocr_confidence=confidence, known_invoices=known)
        repository.save_issues(document_id, [issue.model_dump() for issue in result.issues])

        final_status = "needs_review" if result.needs_review else "completed"
        repository.set_status(document_id, final_status, needs_review=result.needs_review)

    except (UnsupportedFileError, CorruptedFileError, FileNotFoundError, ExtractionError) as error:
        logger.info("Document %s failed: %s", document_id, error)
        repository.set_status(document_id, "failed", error_message=str(error))
    except Exception as error:  # anything unexpected: still never crash the worker
        logger.exception("Unexpected error while processing document %s", document_id)
        repository.set_status(document_id, "failed", error_message=f"Unexpected error: {error}")