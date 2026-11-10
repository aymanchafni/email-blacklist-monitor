"""Text extraction from attachments (PDF, Excel, CSV, images via OCR)."""

from __future__ import annotations

import io
import logging
from pathlib import PurePath

import pandas as pd

logger = logging.getLogger(__name__)

SPREADSHEET = {".xlsx", ".xlsm", ".xls"}
IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
SUPPORTED = {".pdf", ".csv", ".txt"} | SPREADSHEET | IMAGES


def is_supported(filename: str) -> bool:
    return PurePath(filename).suffix.lower() in SUPPORTED


def _frame_to_text(df: pd.DataFrame) -> str:
    # One line per row, cells separated by " | ". (DataFrame.to_string() pads columns with
    # spaces, which breaks phrase matching such as "first last" across two columns.)
    return "\n".join(" | ".join("" if pd.isna(v) else str(v) for v in row) for row in df.itertuples(index=False))


def pdf_text(content: bytes) -> str:
    import fitz  # PyMuPDF

    with fitz.open(stream=content, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def spreadsheet_text(content: bytes, filename: str) -> str:
    engine = "xlrd" if filename.lower().endswith(".xls") else "openpyxl"
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=str, engine=engine)
    return "\n".join(f"{name}\n{_frame_to_text(df)}" for name, df in sheets.items())


def csv_text(content: bytes) -> str:
    df = pd.read_csv(io.BytesIO(content), header=None, dtype=str, sep=None, engine="python")
    return _frame_to_text(df)


def image_text(content: bytes, tesseract_cmd: str | None = None) -> str:
    import pytesseract
    from PIL import Image

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    return pytesseract.image_to_string(Image.open(io.BytesIO(content)))


def extract_text(content: bytes, filename: str, tesseract_cmd: str | None = None) -> str:
    """Return the text of an attachment. Raises on corrupt files: the caller decides
    whether to retry, so failures are never silently treated as 'no match'."""
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".pdf":
        return pdf_text(content)
    if suffix in SPREADSHEET:
        return spreadsheet_text(content, filename)
    if suffix == ".csv":
        return csv_text(content)
    if suffix == ".txt":
        return content.decode("utf-8", errors="replace")
    if suffix in IMAGES:
        return image_text(content, tesseract_cmd)
    raise ValueError(f"Unsupported attachment type: {filename}")
