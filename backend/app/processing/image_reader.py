"""Read text from image files (JPG, PNG, TIFF) using OCR.

Photos and scans are often blurry, small or low contrast, so we clean the image
a little before OCR. OCR is never perfect, so we also return a confidence score
(0-100) that later steps can use to flag uncertain results for manual review.
"""

import os
import shutil
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from backend.app.processing.file_types import CorruptedFileError

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
MIN_WIDTH = 1500  # small images are enlarged so OCR can read small text


def _configure_tesseract() -> None:
    """Tell pytesseract where the Tesseract program is installed."""
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not cmd and Path(DEFAULT_TESSERACT).exists():
        cmd = DEFAULT_TESSERACT
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd


_configure_tesseract()


def preprocess(image: Image.Image) -> Image.Image:
    """Make an image easier for OCR: fix rotation, grayscale, contrast, size."""
    image = ImageOps.exif_transpose(image)  # fixes rotated phone photos
    image = image.convert("L")
    image = ImageOps.autocontrast(image)
    if image.width < MIN_WIDTH:
        scale = MIN_WIDTH / image.width
        new_size = (MIN_WIDTH, int(image.height * scale))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    return image


def ocr_image(image: Image.Image) -> dict:
    """Run OCR on one image. Returns {"text": str, "confidence": float}."""
    prepared = preprocess(image)
    text = pytesseract.image_to_string(prepared).strip()

    data = pytesseract.image_to_data(prepared, output_type=pytesseract.Output.DICT)
    scores = [
        float(conf)
        for conf, word in zip(data["conf"], data["text"])
        if word.strip() and float(conf) >= 0
    ]
    confidence = round(sum(scores) / len(scores), 1) if scores else 0.0
    return {"text": text, "confidence": confidence}


def read_image(path: str) -> list[dict]:
    """Return one dict per page/frame: {"page": 1, "text": "...", "confidence": 93.5}.

    A multi-page TIFF gives several entries; JPG and PNG give one.
    """
    try:
        with Image.open(path) as img:
            results = []
            for index, frame in enumerate(ImageSequence.Iterator(img), start=1):
                result = ocr_image(frame.copy())
                results.append({"page": index, **result})
    except (UnidentifiedImageError, OSError) as exc:
        raise CorruptedFileError(f"Cannot open image: {exc}") from exc
    return results