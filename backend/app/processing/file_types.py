"""Detect the real type of an uploaded file.

We never trust the file extension alone. We also check the file's first
bytes (its "magic bytes") so a renamed or corrupted file is caught early.
"""

from pathlib import Path


class UnsupportedFileError(Exception):
    """The file type is not one we accept."""


class CorruptedFileError(Exception):
    """The file is empty, damaged, or its content does not match its extension."""


# extension -> the kind of pipeline that should handle it
EXTENSION_TO_KIND = {
    ".pdf": "pdf",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".tif": "image",
    ".tiff": "image",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".csv": "csv",
}


def _matches_signature(ext: str, header: bytes) -> bool:
    """Check that the file's first bytes match what its extension claims."""
    if ext == ".pdf":
        return b"%PDF" in header[:1024]
    if ext in (".jpg", ".jpeg"):
        return header.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".tif", ".tiff"):
        return header[:4] in (b"II*\x00", b"MM\x00*")
    if ext == ".xlsx":
        return header.startswith(b"PK\x03\x04")  # xlsx is a zip file inside
    if ext == ".xls":
        return header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if ext == ".csv":
        return b"\x00" not in header  # a real text file has no null bytes
    return False


def detect_file_kind(path: str) -> str:
    """Return 'pdf', 'image', 'spreadsheet' or 'csv' for a valid file.

    Raises:
        FileNotFoundError: the path does not exist.
        UnsupportedFileError: the extension is not supported.
        CorruptedFileError: the file is empty or its content does not match.
    """
    file_path = Path(path)

    if not file_path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    ext = file_path.suffix.lower()
    kind = EXTENSION_TO_KIND.get(ext)
    if kind is None:
        raise UnsupportedFileError(f"Unsupported file type: '{ext}'")

    if file_path.stat().st_size == 0:
        raise CorruptedFileError("File is empty")

    with open(file_path, "rb") as f:
        header = f.read(2048)

    if not _matches_signature(ext, header):
        raise CorruptedFileError(
            f"File content does not look like a valid '{ext}' file"
        )

    return kind