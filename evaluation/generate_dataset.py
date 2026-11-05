"""Generate a small LABELLED evaluation dataset of FABRICATED invoices.

Everything here is invented: companies, people, addresses and amounts. No real
document or personal data is used. The script is deterministic (fixed seed), so
anybody can regenerate the exact same dataset and reproduce the evaluation.

For every file we also write the correct answer (ground truth) to labels.json.
Some invoices contain deliberate mistakes, so we can measure whether the
validator catches them. Two files are broken on purpose to test failure handling.
"""

import copy
import csv
import json
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pymupdf
from openpyxl import Workbook
from PIL import Image, ImageFilter

OUT_DIR = Path(__file__).resolve().parent / "dataset"
rng = random.Random(2026)

SUPPLIERS = [
    ("Sunrise Trading Ltd", "House 12, Road 5, Dhanmondi, Dhaka", "BDT"),
    ("Northwind Supplies", "42 Harbor Street, Rotterdam", "EUR"),
    ("Acme Industrial Co", "18 Market Road, Austin TX", "USD"),
    ("Blue River Stationers", "7 Lake View, Chittagong", "BDT"),
    ("Greenleaf Foods", "221 Orchard Lane, Leeds", "GBP"),
    ("Pioneer Tech Services", "90 Silicon Avenue, Singapore", "USD"),
]
CUSTOMERS = [
    "Greenfield Traders", "Delta Office Solutions", "Horizon Retail Pvt", "Maple Leaf Clinic",
    "Riverside Hotel", "Orbit Logistics", "Sakura Imports", "Bright Future School",
]
CATALOG = [
    ("Office Chair", 2500.0), ("Desk Lamp", 450.0), ("A4 Paper Ream", 620.0), ("Printer Toner", 3800.0),
    ("Whiteboard", 1750.0), ("USB Keyboard", 1200.0), ("Monitor Stand", 980.0),
    ("Filing Cabinet", 6400.0), ("Stapler Set", 320.0), ("Network Cable 10m", 260.0),
]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def money(value: float) -> str:
    return f"{value:,.2f}"


def fmt_date(iso: str, style: int) -> str:
    d = date.fromisoformat(iso)
    if style == 0:
        return d.isoformat()
    if style == 1:
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    return f"{MONTHS[d.month - 1][:3]} {d.day}, {d.year}"


def make_invoice(number, *, tax_rate=0.05, with_due=True, with_currency=True, date_style=0, n_items=None):
    """Build one invoice. The dict holds exactly what is PRINTED, so it is also the truth."""
    supplier = rng.choice(SUPPLIERS)
    rows = []
    for name, price in rng.sample(CATALOG, n_items or rng.randint(2, 5)):
        qty = rng.randint(1, 12)
        rows.append({"description": name, "quantity": float(qty), "unit_price": price,
                     "amount": round(qty * price, 2)})
    subtotal = round(sum(r["amount"] for r in rows), 2)
    tax = round(subtotal * tax_rate, 2) if tax_rate else None
    issued = date(2026, rng.randint(1, 10), rng.randint(1, 28))
    due = issued + timedelta(days=rng.choice([14, 30, 45]))
    return {
        "invoice_number": number,
        "invoice_date": issued.isoformat(),
        "due_date": due.isoformat() if with_due else None,
        "supplier_name": supplier[0],
        "supplier_address": supplier[1],
        "customer_name": rng.choice(CUSTOMERS),
        "currency": supplier[2] if with_currency else None,
        "subtotal": subtotal,
        "tax": tax,
        "tax_rate": tax_rate,
        "total": round(subtotal + (tax or 0), 2),
        "line_items": rows,
        "date_style": date_style,
    }


def expected(inv: dict) -> dict:
    keys = ("invoice_number", "invoice_date", "due_date", "supplier_name", "customer_name",
            "currency", "subtotal", "tax", "total")
    result = {k: inv[k] for k in keys}
    result["line_items"] = [
        {k: r[k] for k in ("description", "quantity", "unit_price", "amount")} for r in inv["line_items"]
    ]
    return result


def draw_invoice(inv: dict) -> "pymupdf.Document":
    doc = pymupdf.open()
    page = doc.new_page()

    def put(x, y, text, size=11, font="helv"):
        page.insert_text((x, y), text, fontsize=size, fontname=font)

    put(50, 60, inv["supplier_name"].upper(), 16, "hebo")
    put(50, 78, inv["supplier_address"], 10)
    put(50, 120, "INVOICE", 20, "hebo")
    y = 150
    if inv["invoice_number"]:
        put(50, y, f"Invoice No: {inv['invoice_number']}")
        y += 18
    if inv["invoice_date"]:
        put(50, y, f"Date: {fmt_date(inv['invoice_date'], inv['date_style'])}")
        y += 18
    if inv["due_date"]:
        put(50, y, f"Due Date: {fmt_date(inv['due_date'], inv['date_style'])}")
        y += 18
    put(50, y, f"Bill To: {inv['customer_name']}")
    y += 32
    for x, label in ((50, "Description"), (300, "Qty"), (360, "Unit Price"), (470, "Amount")):
        put(x, y, label, 11, "hebo")
    y += 20
    for r in inv["line_items"]:
        put(50, y, r["description"])
        put(300, y, str(int(r["quantity"])))
        put(360, y, money(r["unit_price"]))
        put(470, y, money(r["amount"]))
        y += 18
    y += 14
    put(360, y, f"Subtotal: {money(inv['subtotal'])}")
    y += 18
    if inv["tax"] is not None:
        put(360, y, f"Tax ({round(inv['tax_rate'] * 100)}%): {money(inv['tax'])}")
        y += 18
    put(360, y, f"Total: {money(inv['total'])}", 12, "hebo")
    y += 28
    if inv["currency"]:
        put(50, y, f"Currency: {inv['currency']}")
    return doc


def sheet_rows(inv: dict) -> list:
    rows = [["Invoice No", inv["invoice_number"]], ["Date", inv["invoice_date"]]]
    if inv["due_date"]:
        rows.append(["Due Date", inv["due_date"]])
    rows += [["Supplier", inv["supplier_name"]], ["Bill To", inv["customer_name"]]]
    if inv["currency"]:
        rows.append(["Currency", inv["currency"]])
    rows += [[], ["Description", "Qty", "Unit Price", "Amount"]]
    for r in inv["line_items"]:
        rows.append([r["description"], str(int(r["quantity"])), f"{r['unit_price']:.2f}", f"{r['amount']:.2f}"])
    rows.append(["Subtotal", "", "", f"{inv['subtotal']:.2f}"])
    if inv["tax"] is not None:
        rows.append(["Tax", "", "", f"{inv['tax']:.2f}"])
    rows.append(["Total", "", "", f"{inv['total']:.2f}"])
    return rows


def label(file, kind, inv=None, issues=(), fail=False, notes=""):
    return {
        "file": file,
        "kind": kind,
        "expected": expected(inv) if inv else None,
        "expected_issue_codes": list(issues),
        "expect_failure": fail,
        "notes": notes,
    }


def main() -> None:
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    OUT_DIR.mkdir(parents=True)
    labels = []

    def pdf(name, inv, issues=(), notes=""):
        doc = draw_invoice(inv)
        doc.save(str(OUT_DIR / name))
        doc.close()
        labels.append(label(name, "pdf", inv, issues, notes=notes))

    def scan(name, inv, blur, angle, noise, notes=""):
        doc = draw_invoice(inv)
        pix = doc[0].get_pixmap(dpi=110)
        doc.close()
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        img = img.rotate(angle, expand=True, fillcolor=255, resample=Image.Resampling.BICUBIC)
        img = img.filter(ImageFilter.GaussianBlur(blur))
        arr = np.asarray(img, dtype=np.float32)
        arr = arr + np.random.default_rng(7).normal(0, noise, arr.shape)
        Image.fromarray(np.clip(arr, 0, 255).astype("uint8")).save(OUT_DIR / name)
        labels.append(label(name, "scan", inv, notes=notes))

    def sheet_csv(name, inv):
        with open(OUT_DIR / name, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(sheet_rows(inv))
        labels.append(label(name, "csv", inv))

    def sheet_xlsx(name, inv):
        wb = Workbook()
        ws = wb.active
        for row in sheet_rows(inv):
            ws.append(row)
        wb.save(OUT_DIR / name)
        labels.append(label(name, "xlsx", inv))

    # ---- clean documents: no validation issue expected ----
    inv1 = make_invoice("INV-1001", tax_rate=0.05, date_style=0)
    pdf("01_pdf_basic.pdf", inv1, notes="digital PDF, ISO date")
    pdf("02_pdf_long_date.pdf", make_invoice("2026/0042", tax_rate=0.10, date_style=1), notes="date like 15 October 2026")
    pdf("03_pdf_no_tax_no_due.pdf",
        make_invoice("A-7781", tax_rate=None, with_due=False, with_currency=False, date_style=2),
        notes="tax, due date and currency are NOT printed: the correct answer is null")
    pdf("04_pdf_leading_zeros.pdf", make_invoice("00427", tax_rate=0.10, date_style=1), notes="invoice number with leading zeros")
    pdf("05_pdf_tax15.pdf", make_invoice("INV-1005", tax_rate=0.15, date_style=2))
    pdf("06_pdf_many_items.pdf", make_invoice("INV-1006", tax_rate=0.05, n_items=8), notes="8 line items")
    scan("07_scan_light.png", make_invoice("INV-1007", tax_rate=0.05), blur=0.4, angle=0.5, noise=3, notes="light scan")
    scan("08_scan_medium.png", make_invoice("INV-1008", tax_rate=0.10), blur=0.9, angle=1.5, noise=9, notes="medium scan")
    scan("09_scan_heavy.png", make_invoice("INV-1009", tax_rate=0.05), blur=1.5, angle=2.5, noise=16, notes="poor scan")
    sheet_csv("10_sheet.csv", make_invoice("INV-1010", tax_rate=0.05))
    sheet_csv("11_sheet_no_tax.csv", make_invoice("INV-1011", tax_rate=None, with_currency=False))
    sheet_xlsx("12_sheet.xlsx", make_invoice("INV-1012", tax_rate=0.10))
    sheet_xlsx("13_sheet_tax.xlsx", make_invoice("INV-1013", tax_rate=0.15, with_due=False))
    pdf("14_pdf_leading_zeros_2.pdf", make_invoice("000831", tax_rate=0.05), notes="invoice number with leading zeros")

    # ---- deliberate mistakes: the validator should catch them ----
    bad = make_invoice("INV-1015", tax_rate=0.05)
    bad["total"] = round(bad["total"] + 500, 2)
    pdf("15_flaw_wrong_total.pdf", bad, ["total_mismatch"], "printed total is 500 too high")

    bad = make_invoice("INV-1016", tax_rate=0.05)
    bad["line_items"][0]["amount"] = round(bad["line_items"][0]["amount"] + 100, 2)
    bad["subtotal"] = round(sum(r["amount"] for r in bad["line_items"]), 2)
    bad["tax"] = round(bad["subtotal"] * 0.05, 2)
    bad["total"] = round(bad["subtotal"] + bad["tax"], 2)
    pdf("16_flaw_wrong_line.pdf", bad, ["line_total_mismatch"], "first line: qty x price differs from amount")

    bad = make_invoice("INV-1017", tax_rate=0.05)
    bad["invoice_date"] = None
    pdf("17_flaw_no_date.pdf", bad, ["missing_field"], "invoice date is not printed")

    bad = make_invoice("INV-1018", tax_rate=0.05)
    bad["invoice_number"] = None
    pdf("18_flaw_no_number.pdf", bad, ["missing_field"], "invoice number is not printed")

    dup = copy.deepcopy(inv1)
    dup["date_style"] = 1
    pdf("19_flaw_duplicate.pdf", dup, ["duplicate_invoice"], "same supplier + invoice number as file 01")

    # ---- broken files: the system must fail safely ----
    (OUT_DIR / "20_corrupt.pdf").write_bytes(b"%PDF-1.4\n" + bytes(rng.randrange(256) for _ in range(600)))
    labels.append(label("20_corrupt.pdf", "corrupt", fail=True, notes="starts like a PDF but is garbage"))
    (OUT_DIR / "21_unsupported.txt").write_text("This is not a supported invoice format.\n", encoding="utf-8")
    labels.append(label("21_unsupported.txt", "unsupported", fail=True, notes="unsupported file type"))

    with open(OUT_DIR / "labels.json", "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(labels)} files and labels.json to {OUT_DIR}")


if __name__ == "__main__":
    main()