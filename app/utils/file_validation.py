"""
Validates uploaded files without trusting anything the browser claims.
The browser's Content-Type header and the filename extension are both
just labels the client chose — we verify the actual file bytes too.
"""

from io import BytesIO

import pdfplumber
from fastapi import UploadFile

from app.core.config import settings

PDF_MAGIC_BYTES = b"%PDF-"
DANGEROUS_EXTENSIONS = {".exe", ".zip", ".js", ".py", ".bat", ".sh", ".cmd", ".msi", ".dll"}


class FileValidationError(Exception):
    pass


def get_pdf_page_count(file_bytes: bytes) -> int:
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
    except Exception as exc:
        raise FileValidationError("This PDF couldn't be read to determine its page count.") from exc

    if page_count == 0:
        raise FileValidationError("This PDF doesn't contain any pages.")

    return page_count


def validate_pdf_upload(file: UploadFile, file_bytes: bytes) -> None:
    filename = (file.filename or "").lower()

    if not filename.endswith(".pdf"):
        raise FileValidationError("Only PDF files are accepted.")

    for ext in DANGEROUS_EXTENSIONS:
        if filename.endswith(ext):
            raise FileValidationError("This file type isn't allowed.")

    # Magic-byte check: a real PDF starts with "%PDF-" regardless of what
    # its extension or Content-Type header claims.
    if not file_bytes[:5] == PDF_MAGIC_BYTES:
        raise FileValidationError("This file doesn't look like a valid PDF.")

    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise FileValidationError(
            f"File is too large ({size_mb:.1f} MB). Max is {settings.MAX_UPLOAD_SIZE_MB} MB."
        )

    if len(file_bytes) == 0:
        raise FileValidationError("The uploaded file is empty.")
