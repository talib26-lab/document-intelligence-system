"""Turn the text of a processed document into structured invoice data using Gemini.

Design rules:
- The model may only copy what the document shows. Missing values must be null.
- temperature=0 so the same document gives the same answer (needed for evaluation).
- The reply is validated against the InvoiceData schema before we trust it.
"""

import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

from backend.app.extraction.schemas import InvoiceData

load_dotenv()

MODEL_NAME = "gemini-2.5-flash"  # pinned on purpose, so results are reproducible
MAX_ATTEMPTS = 3

SYSTEM_PROMPT = """You extract structured data from invoices.

Rules you must follow:
1. Use ONLY information that is written in the document text.
2. If a value is not clearly shown, return null. Never guess or invent values.
3. Never calculate a value yourself. Do not add up numbers to fill a missing total.
4. Copy numbers exactly as written. Remove currency symbols and thousand separators.
5. Dates must be YYYY-MM-DD. If the date is ambiguous, return null and list it in uncertain_fields.
6. Keep the invoice number exactly as written, including leading zeros.
7. If the text looks garbled or a value is hard to read, list that field in uncertain_fields.
"""


class ExtractionError(Exception):
    """Raised when the AI could not produce a usable result."""


def build_document_text(processed: dict) -> str:
    """Join the text of all pages from process_document() into one string."""
    parts = []
    for page in processed.get("pages", []):
        text = (page.get("text") or "").strip()
        if text:
            parts.append(f"--- Page {page.get('page')} ---\n{text}")
    return "\n\n".join(parts)


def extract_invoice(document_text: str) -> InvoiceData:
    """Send the document text to Gemini and return validated InvoiceData."""
    if not document_text.strip():
        raise ExtractionError("There is no text to extract from.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ExtractionError("GEMINI_API_KEY is missing. Check your .env file.")

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0,
        response_mime_type="application/json",
        response_schema=InvoiceData,
    )

    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=document_text,
                config=config,
            )
            return InvoiceData.model_validate_json(response.text)
        except Exception as error:  # network, rate limit, or invalid reply
            last_error = error
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 * attempt)  # wait a little longer each time

    raise ExtractionError(f"Extraction failed after {MAX_ATTEMPTS} attempts: {last_error}")