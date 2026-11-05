## Overall (field level)

| Metric | Result |
|---|---|
| Documents with ground truth | 19 |
| Field accuracy (correct value or correctly null) | 87.7% (150/171) |
| Hallucination rate (value invented where truth is null) | 0.0% (0/8) |
| Missed rate (truth has a value, AI returned null) | 10.4% (17/163) |
| Wrong-value rate (value present but different) | 2.5% (4/163) |
| Fully correct documents (all fields + all line items) | 78.9% (15/19) |
| Line-item recall | 80.0% (68/85) |
| Line-item precision | 91.9% (68/74) |

## Per field

| Field | Accuracy | Hallucinated | Missed | Wrong |
|---|---|---|---|---|
| invoice_number | 89.5% (17/19) | 0 | 1 | 1 |
| invoice_date | 84.2% (16/19) | 0 | 2 | 1 |
| due_date | 89.5% (17/19) | 0 | 2 | 0 |
| supplier_name | 89.5% (17/19) | 0 | 2 | 0 |
| customer_name | 84.2% (16/19) | 0 | 2 | 1 |
| currency | 89.5% (17/19) | 0 | 2 | 0 |
| subtotal | 84.2% (16/19) | 0 | 2 | 1 |
| tax | 89.5% (17/19) | 0 | 2 | 0 |
| total | 89.5% (17/19) | 0 | 2 | 0 |

## By input type (field accuracy)

| Group | Documents | Field accuracy | Fully correct docs |
|---|---|---|---|
| csv | 2 | 100.0% (18/18) | 100.0% (2/2) |
| pdf | 12 | 84.3% (91/108) | 83.3% (10/12) |
| scan | 3 | 85.2% (23/27) | 33.3% (1/3) |
| scan: heavy.png | 1 | 55.6% (5/9) | 0.0% (0/1) |
| scan: light.png | 1 | 100.0% (9/9) | 100.0% (1/1) |
| scan: medium.png | 1 | 100.0% (9/9) | 0.0% (0/1) |
| xlsx | 2 | 100.0% (18/18) | 100.0% (2/2) |

## Validation

| Check | Result |
|---|---|
| Injected errors detected (expected code present) | 60.0% (3/5) |
| Clean documents wrongly flagged for review | 14.3% (2/14) |

Per injected error:

| File | Expected | Found | Detected |
|---|---|---|---|
| 15_flaw_wrong_total.pdf | total_mismatch | total_mismatch | yes |
| 16_flaw_wrong_line.pdf | line_total_mismatch | line_total_mismatch | yes |
| 17_flaw_no_date.pdf | missing_field | missing_field | yes |
| 18_flaw_no_number.pdf | missing_field | - | NO |
| 19_flaw_duplicate.pdf | duplicate_invoice | - | NO |

## Failure handling

| File | Status | Safe failure with message |
|---|---|---|
| 20_corrupt.pdf | failed | yes |
| 21_unsupported.txt | failed | yes |

## Speed (includes the Gemini call)

Mean 5.7s, median 4.8s, max 11.7s per document (19 documents).