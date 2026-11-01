"""Read spreadsheet files (XLSX, XLS, CSV) into plain rows of text.

Every cell is read as text, so an invoice number like "00123" is never
turned into the number 123. We do not guess which row is the header;
that is decided later, when the data is interpreted.
"""

import csv
from pathlib import Path

import pandas as pd

from backend.app.processing.file_types import (
    CorruptedFileError,
    UnsupportedFileError,
)

# CSV files come in different encodings; we try the common ones in order.
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _clean(df: pd.DataFrame) -> list[list[str]]:
    """Turn a table into rows of stripped text, dropping fully empty rows/columns."""
    df = df.fillna("").astype(str).apply(lambda col: col.str.strip())
    has_value = df != ""
    df = df.loc[has_value.any(axis=1), has_value.any(axis=0)]
    return df.values.tolist()


def _read_csv(path: str) -> list[dict]:
    rows = None
    for encoding in CSV_ENCODINGS:
        try:
            with open(path, newline="", encoding=encoding) as f:
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                except csv.Error:
                    dialect = csv.excel
                rows = [[cell.strip() for cell in row] for row in csv.reader(f, dialect)]
            break
        except UnicodeDecodeError:
            continue
        except csv.Error as exc:
            raise CorruptedFileError(f"Cannot parse CSV: {exc}") from exc

    if rows is None:
        raise CorruptedFileError("Cannot decode CSV file")

    rows = [row for row in rows if any(row)]
    return [{"sheet": "csv", "rows": rows}]


def _read_excel(path: str) -> list[dict]:
    try:
        sheets = pd.read_excel(
            path,
            sheet_name=None,  # read every sheet
            header=None,  # keep all rows, do not guess a header
            dtype=str,  # keep everything as text
            keep_default_na=False,
        )
    except Exception as exc:
        raise CorruptedFileError(f"Cannot open spreadsheet: {exc}") from exc

    return [{"sheet": str(name), "rows": _clean(df)} for name, df in sheets.items()]


def read_spreadsheet(path: str) -> list[dict]:
    """Return one dict per sheet: {"sheet": "Sheet1", "rows": [["a", "b"], ...]}.

    Raises:
        UnsupportedFileError: the extension is not csv/xlsx/xls.
        CorruptedFileError: the file cannot be read or contains no data.
    """
    ext = Path(path).suffix.lower()
    if ext == ".csv":
        result = _read_csv(path)
    elif ext in (".xlsx", ".xls"):
        result = _read_excel(path)
    else:
        raise UnsupportedFileError(f"Not a spreadsheet type: '{ext}'")

    if not any(sheet["rows"] for sheet in result):
        raise CorruptedFileError("Spreadsheet contains no data")
    return result