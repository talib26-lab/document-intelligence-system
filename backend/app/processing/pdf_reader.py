"""Extract text from PDF files, page by page.

Digital PDFs already contain real text, so we read it directly (fast and exact).
Pages with almost no text are probably scanned images; we flag them so the
OCR step can handle them later.
"""

import pymupdf

from backend.app.processing.file_types import CorruptedFileError

# A page with fewer characters than this is treated as "no real text".
MIN_TEXT_CHARS = 20


def read_pdf(path: str) -> list[dict]:
    """Return one dict per page: {"page": 1, "text": "...", "needs_ocr": False}."""
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise CorruptedFileError(f"Cannot open PDF: {exc}") from exc

    with doc:
        if doc.needs_pass:
            raise CorruptedFileError("PDF is password protected")

        pages = []
        for index, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            pages.append(
                {
                    "page": index,
                    "text": text,
                    "needs_ocr": len(text) < MIN_TEXT_CHARS,
                }
            )
    return pages