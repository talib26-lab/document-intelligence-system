"""Run the REAL pipeline (run_job + Gemini) on the labelled dataset and MEASURE it.

Nothing here is estimated: every number comes from comparing what the system
produced with the ground truth in dataset/labels.json. A temporary database is
used, so your real data is never touched.

Usage:
    python evaluation/run_evaluation.py --limit 3     (quick trial, 3 files)
    python evaluation/run_evaluation.py               (all files)
"""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# IMPORTANT: point the app to a throw-away database BEFORE importing it.
TMP_DIR = Path(tempfile.mkdtemp(prefix="docint_eval_"))
os.environ["DATABASE_PATH"] = str(TMP_DIR / "eval.db")

from backend.app.db import repository  # noqa: E402
from backend.app.db.database import init_db  # noqa: E402
from backend.app.services.job_runner import run_job  # noqa: E402

DATASET = Path(__file__).resolve().parent / "dataset"
RESULTS = Path(__file__).resolve().parent / "results"
FIELDS = ["invoice_number", "invoice_date", "due_date", "supplier_name",
          "customer_name", "currency", "subtotal", "tax", "total"]
NUMERIC = {"subtotal", "tax", "total"}
DATES = {"invoice_date", "due_date"}
SLEEP_BETWEEN_AI_CALLS = 5  # seconds, to stay inside free-tier rate limits

# ---------------------------------------------------------------- AI answer cache
import hashlib  # noqa: E402

from backend.app.extraction.invoice_extractor import MODEL_NAME, extract_invoice  # noqa: E402
from backend.app.extraction.schemas import InvoiceData  # noqa: E402

CACHE_PATH = RESULTS / "ai_cache.json"
STATS = {"live": 0, "cached": 0}


def cached_extract(text: str):
    """Ask Gemini only if we have never seen this exact document text with this model.

    Only SUCCESSFUL answers are stored (errors propagate), so a rate-limit failure
    can never end up in the cache.
    """
    key = hashlib.sha256((MODEL_NAME + "\n" + text).encode("utf-8")).hexdigest()
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    if key in cache:
        STATS["cached"] += 1
        return InvoiceData.model_validate(cache[key])
    STATS["live"] += 1
    invoice = extract_invoice(text)
    cache[key] = invoice.model_dump()
    RESULTS.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    return invoice


# ---------------------------------------------------------------- comparison
def is_empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def to_float(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def norm_text(v) -> str:
    return " ".join(str(v).split()).casefold()


def same(field, truth, pred) -> bool:
    if field in NUMERIC:
        a, b = to_float(truth), to_float(pred)
        return a is not None and b is not None and abs(a - b) <= 0.01
    if field == "invoice_number":
        return str(pred).strip() == str(truth).strip()  # leading zeros matter
    if field == "currency":
        return str(pred).strip().upper() == str(truth).strip().upper()
    if field in DATES:
        return str(pred).strip()[:10] == str(truth).strip()
    return norm_text(pred) == norm_text(truth)


def field_outcome(field, truth, pred) -> str:
    if is_empty(truth):
        return "correct_null" if is_empty(pred) else "hallucinated"
    if is_empty(pred):
        return "missed"
    return "correct" if same(field, truth, pred) else "wrong"


def line_items_score(expected, predicted):
    """Match each expected line to an unused predicted line. Returns (matched, n_exp, n_pred)."""
    predicted = [p for p in (predicted or []) if isinstance(p, dict)]
    used, matched = set(), 0
    for e in expected or []:
        for i, p in enumerate(predicted):
            if i in used:
                continue
            desc_ok = norm_text(e["description"]) == norm_text(p.get("description") or "")
            amt_ok = to_float(p.get("amount")) is not None and abs(to_float(p["amount"]) - e["amount"]) <= 0.01
            qty_ok = to_float(p.get("quantity")) is not None and abs(to_float(p["quantity"]) - e["quantity"]) <= 0.01
            if desc_ok and amt_ok and qty_ok:
                used.add(i)
                matched += 1
                break
    return matched, len(expected or []), len(predicted)


# ---------------------------------------------------------------- running
def evaluate_one(entry: dict) -> dict:
    path = DATASET / entry["file"]
    doc_id = repository.create_document(entry["file"], str(path), None)
    start = time.perf_counter()
    crashed = None
    try:
        run_job(doc_id, extractor=cached_extract)
    except Exception as error:  # run_job promises never to raise; record it if it does
        crashed = repr(error)
    elapsed = time.perf_counter() - start

    doc = repository.get_document(doc_id)
    extraction = doc.get("extraction") or {}
    predicted = extraction.get("ai_data") or {}
    issues = doc.get("issues") or []
    result = {
        "file": entry["file"], "kind": entry["kind"], "status": doc.get("status"),
        "error_message": doc.get("error_message"), "crashed": crashed,
        "seconds": round(elapsed, 2), "ocr_confidence": doc.get("ocr_confidence"),
        "issue_codes": sorted({i["code"] for i in issues}),
        "predicted": predicted, "expected": entry["expected"],
        "expected_issue_codes": entry["expected_issue_codes"],
        "expect_failure": entry["expect_failure"],
    }
    if entry["expected"]:
        result["fields"] = {f: field_outcome(f, entry["expected"].get(f), predicted.get(f)) for f in FIELDS}
        m, ne, npred = line_items_score(entry["expected"]["line_items"], predicted.get("line_items"))
        result["lines"] = {"matched": m, "expected": ne, "predicted": npred}
        result["fully_correct"] = (all(v in ("correct", "correct_null") for v in result["fields"].values())
                                   and m == ne == npred)
    return result


# ---------------------------------------------------------------- summary
def pct(n, d) -> str:
    return f"{100 * n / d:.1f}% ({n}/{d})" if d else "n/a"


def field_stats(rows):
    c = Counter()
    per_field = defaultdict(Counter)
    for r in rows:
        for f, o in r.get("fields", {}).items():
            c[o] += 1
            per_field[f][o] += 1
    return c, per_field


def build_summary(results: list) -> str:
    out = []
    ok = [r for r in results if r.get("fields")]
    c, per_field = field_stats(ok)
    total = sum(c.values())
    truth_null = c["correct_null"] + c["hallucinated"]
    truth_val = c["correct"] + c["missed"] + c["wrong"]

    out.append("## Overall (field level)\n")
    out.append("| Metric | Result |\n|---|---|")
    out.append(f"| Documents with ground truth | {len(ok)} |")
    out.append(f"| Field accuracy (correct value or correctly null) | {pct(c['correct'] + c['correct_null'], total)} |")
    out.append(f"| Hallucination rate (value invented where truth is null) | {pct(c['hallucinated'], truth_null)} |")
    out.append(f"| Missed rate (truth has a value, AI returned null) | {pct(c['missed'], truth_val)} |")
    out.append(f"| Wrong-value rate (value present but different) | {pct(c['wrong'], truth_val)} |")
    out.append(f"| Fully correct documents (all fields + all line items) | {pct(sum(r['fully_correct'] for r in ok), len(ok))} |")
    tp, ne, npred = (sum(r["lines"][k] for r in ok) for k in ("matched", "expected", "predicted"))
    out.append(f"| Line-item recall | {pct(tp, ne)} |")
    out.append(f"| Line-item precision | {pct(tp, npred)} |")

    out.append("\n## Per field\n")
    out.append("| Field | Accuracy | Hallucinated | Missed | Wrong |\n|---|---|---|---|---|")
    for f in FIELDS:
        s = per_field[f]
        n = sum(s.values())
        out.append(f"| {f} | {pct(s['correct'] + s['correct_null'], n)} | {s['hallucinated']} | {s['missed']} | {s['wrong']} |")

    out.append("\n## By input type (field accuracy)\n")
    out.append("| Group | Documents | Field accuracy | Fully correct docs |\n|---|---|---|---|")
    groups = defaultdict(list)
    for r in ok:
        groups[r["kind"]].append(r)
        if r["kind"] == "scan":
            groups["scan: " + r["file"].split("_")[2]].append(r)
    for name in sorted(groups):
        rows = groups[name]
        gc, _ = field_stats(rows)
        out.append(f"| {name} | {len(rows)} | {pct(gc['correct'] + gc['correct_null'], sum(gc.values()))} "
                   f"| {pct(sum(r['fully_correct'] for r in rows), len(rows))} |")

    flawed = [r for r in results if r["expected_issue_codes"]]
    clean = [r for r in ok if not r["expected_issue_codes"]]
    out.append("\n## Validation\n")
    out.append("| Check | Result |\n|---|---|")
    out.append(f"| Injected errors detected (expected code present) | "
               f"{pct(sum(set(r['expected_issue_codes']) <= set(r['issue_codes']) for r in flawed), len(flawed))} |")
    out.append(f"| Clean documents wrongly flagged for review | "
               f"{pct(sum(r['status'] == 'needs_review' for r in clean), len(clean))} |")
    out.append("\nPer injected error:\n")
    out.append("| File | Expected | Found | Detected |\n|---|---|---|---|")
    for r in flawed:
        det = set(r["expected_issue_codes"]) <= set(r["issue_codes"])
        out.append(f"| {r['file']} | {', '.join(r['expected_issue_codes'])} | {', '.join(r['issue_codes']) or '-'} | {'yes' if det else 'NO'} |")

    broken = [r for r in results if r["expect_failure"]]
    out.append("\n## Failure handling\n")
    out.append("| File | Status | Safe failure with message |\n|---|---|---|")
    for r in broken:
        safe = r["status"] == "failed" and bool(r["error_message"]) and not r["crashed"]
        out.append(f"| {r['file']} | {r['status']} | {'yes' if safe else 'NO'} |")

    times = [r["seconds"] for r in results if not r["expect_failure"]]
    if times:
        out.append("\n## Speed (includes the Gemini call)\n")
        out.append(f"Mean {statistics.mean(times):.1f}s, median {statistics.median(times):.1f}s, "
                   f"max {max(times):.1f}s per document ({len(times)} documents).")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="only the first N files")
    args = parser.parse_args()

    entries = json.loads((DATASET / "labels.json").read_text(encoding="utf-8"))
    if args.limit:
        entries = entries[: args.limit]
    init_db()
    print(f"Temporary database: {os.environ['DATABASE_PATH']}")

    results = []
    for n, entry in enumerate(entries, 1):
        before = STATS["live"]
        r = evaluate_one(entry)
        results.append(r)
        print(f"[{n}/{len(entries)}] {entry['file']:<28} status={r['status']:<13} {r['seconds']:>5}s "
              f"issues={','.join(r['issue_codes']) or '-'}")
        if STATS["live"] > before and n < len(entries):
            time.sleep(SLEEP_BETWEEN_AI_CALLS)

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = build_summary(results)
    (RESULTS / "summary.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)
    print(f"\nSaved: {RESULTS / 'results.json'} and {RESULTS / 'summary.md'}")


if __name__ == "__main__":
    main()