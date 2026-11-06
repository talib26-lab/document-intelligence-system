# AI Usage Disclosure

This document covers two different things: (1) the AI that runs **inside** the product and the exact prompt it receives, and (2) how AI assistance was used to **build** the product.

## 1. AI inside the product: invoice extraction

| Setting | Value | Why |
|---|---|---|
| Model | `gemini-2.5-flash` (pinned, not "latest") | Reproducible evaluation: the same model produces the same behaviour |
| Temperature | `0` | The same document should give the same answer |
| Output format | `application/json` with `response_schema = InvoiceData` | The model must answer in our schema; free text is not accepted |
| Output check | Reply validated with Pydantic (`InvoiceData.model_validate_json`) before it is trusted | Malformed replies are rejected, not stored |
| Retries | 3 attempts, waiting 2 s then 4 s between them | Survives transient network and rate-limit errors |
| Failure | After 3 attempts an `ExtractionError` is raised; the document becomes `failed` with a readable message and can be reprocessed | One bad call never crashes the system |

### The system prompt (verbatim from `backend/app/extraction/invoice_extractor.py`)

```
You extract structured data from invoices.

Rules you must follow:
1. Use ONLY information that is written in the document text.
2. If a value is not clearly shown, return null. Never guess or invent values.
3. Never calculate a value yourself. Do not add up numbers to fill a missing total.
4. Copy numbers exactly as written. Remove currency symbols and thousand separators.
5. Dates must be YYYY-MM-DD. If the date is ambiguous, return null and list it in uncertain_fields.
6. Keep the invoice number exactly as written, including leading zeros.
7. If the text looks garbled or a value is hard to read, list that field in uncertain_fields.
```

### Why each rule exists

| Rule | Problem it prevents |
|---|---|
| 1-2 | **Hallucination**: models like to fill gaps with plausible values. A wrong invoice number or total is worse than an empty field. |
| 3 | **Silent "fixing"**: if the model recalculated totals, it would hide exactly the arithmetic errors the validator must catch. |
| 4 | Inconsistent number formats (`1,250.00`, `$1250`) breaking later arithmetic checks. |
| 5 | Ambiguous dates (`03/04/2026`) being guessed as the wrong month. |
| 6 | `00427` becoming `427`, which would break duplicate detection. |
| 7 | Poor OCR being presented with false confidence; uncertain fields are highlighted for the human reviewer. |

### Design choices around the prompt

- **All schema fields are optional.** The model is allowed to say "not present", which makes `null` an easy, valid answer.
- **The AI never has the last word.** A separate rule-based validator (no AI) checks totals, dates, duplicates and OCR quality. Anything suspicious becomes `needs_review`.
- **The AI answer is never overwritten.** It is stored as `data_json`; human corrections go to `corrected_json`.
- **Instructions and document text are kept apart.** The prompt travels as `system_instruction`; the document text is sent separately as `contents`. This reduces, but does **not** eliminate, the risk of instructions hidden inside an uploaded document (prompt injection). Mitigations that do not depend on the model: the output must match the schema, the model has no tools or network access, and all values still pass through the validator and human review.
- **Measured, not assumed.** The evaluation measures hallucination rate (a value returned where the correct answer is `null`) separately from accuracy. See `docs/evaluation_report.md`.

## 2. AI-assisted development

**Tools used:** Claude (Anthropic) as a guide and pair-programmer, through the Claude app.

**How it was used:**

- Discussing the architecture and trade-offs (SQLite + background tasks for the MVP, repository pattern, validator separate from the AI).
- Drafting code and tests step by step, with each step explained before it was used.
- Explaining errors and warnings and suggesting fixes.
- Drafting this documentation, the README and the evaluation harness.

**What was done and verified by me:**

- I created the environment, repository and API key, and typed or pasted every file into the project myself.
- I ran every command and checked the result before moving on. Git history shows the project growing step by step.
- I ran the automated tests (33 passing) and exercised the UI end to end (upload, review, correct, reprocess).
- I ran the evaluation myself. All reported numbers come from `evaluation/run_evaluation.py` comparing real system output with the labelled ground truth. None of them are estimated or written by the assistant.
- The first evaluation run hit the Gemini free-tier daily limit; it is kept as `evaluation/results/run1_quota_limited_*` instead of being hidden or tuned away.

**What I did not do:** I did not use AI-generated invoices or real customer data. The evaluation dataset is fabricated by a deterministic script (`evaluation/generate_dataset.py`, fixed seed).

**Limits of this disclosure:** AI-drafted code can contain mistakes that tests do not cover. The tests and the evaluation reduce that risk but do not remove it, and the evaluation dataset is small and synthetic.