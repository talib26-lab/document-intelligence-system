## Overall (field level)

| Metric | Result |
|---|---|
| Documents with ground truth | 19 |
| Field accuracy (correct value or correctly null) | 97.1% (166/171) |
| Hallucination rate (value invented where truth is null) | 0.0% (0/8) |
| Missed rate (truth has a value, AI returned null) | 0.0% (0/163) |
| Wrong-value rate (value present but different) | 3.1% (5/163) |
| Fully correct documents (all fields + all line items) | 89.5% (17/19) |
| Line-item recall | 90.6% (77/85) |
| Line-item precision | 91.7% (77/84) |

## Per field

| Field | Accuracy | Hallucinated | Missed | Wrong |
|---|---|---|---|---|
| invoice_number | 94.7% (18/19) | 0 | 0 | 1 |
| invoice_date | 94.7% (18/19) | 0 | 0 | 1 |
| due_date | 100.0% (19/19) | 0 | 0 | 0 |
| supplier_name | 100.0% (19/19) | 0 | 0 | 0 |
| customer_name | 94.7% (18/19) | 0 | 0 | 1 |
| currency | 100.0% (19/19) | 0 | 0 | 0 |
| subtotal | 94.7% (18/19) | 0 | 0 | 1 |
| tax | 94.7% (18/19) | 0 | 0 | 1 |
| total | 100.0% (19/19) | 0 | 0 | 0 |

## By input type (field accuracy)

| Group | Documents | Field accuracy | Fully correct docs |
|---|---|---|---|
| csv | 2 | 100.0% (18/18) | 100.0% (2/2) |
| pdf | 12 | 100.0% (108/108) | 100.0% (12/12) |
| scan | 3 | 81.5% (22/27) | 33.3% (1/3) |
| scan: heavy.png | 1 | 44.4% (4/9) | 0.0% (0/1) |
| scan: light.png | 1 | 100.0% (9/9) | 100.0% (1/1) |
| scan: medium.png | 1 | 100.0% (9/9) | 0.0% (0/1) |
| xlsx | 2 | 100.0% (18/18) | 100.0% (2/2) |

## Validation

| Check | Result |
|---|---|
| Injected errors detected (expected code present) | 100.0% (5/5) |
| Clean documents wrongly flagged for review | 14.3% (2/14) |

Per injected error:

| File | Expected | Found | Detected |
|---|---|---|---|
| 15_flaw_wrong_total.pdf | total_mismatch | total_mismatch | yes |
| 16_flaw_wrong_line.pdf | line_total_mismatch | line_total_mismatch | yes |
| 17_flaw_no_date.pdf | missing_field | missing_field | yes |
| 18_flaw_no_number.pdf | missing_field | missing_field | yes |
| 19_flaw_duplicate.pdf | duplicate_invoice | duplicate_invoice | yes |

## Failure handling

| File | Status | Safe failure with message |
|---|---|---|
| 20_corrupt.pdf | failed | yes |
| 21_unsupported.txt | failed | yes |

## Speed (includes the Gemini call)

Mean 0.2s, median 0.0s, max 1.2s per document (19 documents).