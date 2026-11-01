"""One entry point for reading any supported document.

process_document(path) detects the file type, sends it to the right reader,
runs OCR only on pages that have no real text, and always returns the same
shape, so later steps (AI extraction, validation) never care about the format.
"""

from pathlib import Path

import pymupdf
from PIL import Image

from backend.app.processing.file_types import detect_file_kind
from backend.app.processing.image_reader import ocr_image, read_image
from backend.app.processing.pdf_reader import read_pdf
from backend.app.processing.spreadsheet_reader import read_spreadsheet

OCR_DPI = 200  # resolution used when turning a scanned PDF page into an image


def _process_pdf(path: str) -> tuple[list[dict], list[str]]:
    """Read a PDF; OCR only the pages that have no real text."""
    raw_pages = read_pdf(path)
    pages: list[dict] = []
    warnings: list[str] = []

    doc = None
    try:
        if any(p["needs_ocr"] for p in raw_pages):
            doc = pymupdf.open(path)

        for p in raw_pages:
            if not p["needs_ocr"]:
                pages.append(
                    {"page": p["page"], "text": p["text"], "source": "text", "confidence": None}
                )
                continue
            try:
                pix = doc[p["page"] - 1].get_pixmap(dpi=OCR_DPI)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                result = ocr_image(image)
                pages.append(
                    {
                        "page": p["page"],
                        "text": result["text"],
                        "source": "ocr",
                        "confidence": result["confidence"],
                    }
                )
            except Exception as exc:  # one bad page must not stop the whole file
                warnings.append(f"Page {p['page']}: OCR failed ({exc})")
                pages.append(
                    {"page": p["page"], "text": "", "source": "failed", "confidence": None}
                )
    finally:
        if doc is not None:
            doc.close()

    return pages, warnings


def _process_image(path: str) -> tuple[list[dict], list[str]]:
    pages = [
        {
            "page": item["page"],
            "text": item["text"],
            "source": "ocr",
            "confidence": item["confidence"],
        }
        for item in read_image(path)
    ]
    return pages, []


def _process_spreadsheet(path: str) -> tuple[list[dict], list[str]]:
    pages = []
    for number, sheet in enumerate(read_spreadsheet(path), start=1):
        text = "\n".join(" | ".join(row) for row in sheet["rows"])
        pages.append(
            {
                "page": number,
                "sheet": sheet["sheet"],
                "text": text,
                "rows": sheet["rows"],
                "source": "spreadsheet",
                "confidence": None,
            }
        )
    return pages, []


def process_document(path: str) -> dict:
    """Read any supported file and return a uniform result.

    Returns:
        {"file_name": str, "file_type": str, "page_count": int,
         "pages": [{"page", "text", "source", "confidence", ...}],
         "warnings": [str]}

    Raises:
        FileNotFoundError, UnsupportedFileError, CorruptedFileError
    """
    kind = detect_file_kind(path)

    if kind == "pdf":
        pages, warnings = _process_pdf(path)
    elif kind == "image":
        pages, warnings = _process_image(path)
    else:  # "spreadsheet" or "csv"
        pages, warnings = _process_spreadsheet(path)

    if not any(p["text"].strip() for p in pages):
        warnings.append("No readable text was found in this document")

    return {
        "file_name": Path(path).name,
        "file_type": kind,
        "page_count": len(pages),
        "pages": pages,
        "warnings": warnings,
    }