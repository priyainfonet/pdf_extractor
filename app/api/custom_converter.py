"""Custom PDF-to-Excel extraction API, separate from queued conversions."""

import json
import logging
import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.core.deps import get_current_user
from app.models.user import User
from app.services.custom_pdf_excel import CustomExtractionError, build_custom_workbook
from app.utils.file_validation import FileValidationError, validate_pdf_upload


router = APIRouter(prefix="/api/custom-converter", tags=["custom-converter"])
logger = logging.getLogger("custom_converter_api")


class NormalizedBox(BaseModel):
    """Bounding box as page fractions, origin at the page's top-left."""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def check_dimensions(self):
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("Bounding box must have positive width and height.")
        return self


class PixelBox(BaseModel):
    """Tesseract.js bounding box in source-image pixels."""

    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)

    @model_validator(mode="after")
    def check_dimensions(self):
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("OCR word bounding box must have positive width and height.")
        return self


class MappingSelection(BaseModel):
    page_number: int = Field(alias="pageNumber", ge=1)
    text: str = Field(min_length=1, max_length=4000)
    header: str = Field(min_length=1, max_length=64)
    column: str = Field(pattern=r"^[A-Z]$")
    bbox: NormalizedBox


class OcrWord(BaseModel):
    text: str = Field(min_length=1)
    bbox: PixelBox


class OcrPage(BaseModel):
    page_number: int = Field(alias="pageNumber", ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    words: list[OcrWord]


@router.post(
    "/export",
    summary="Extract selected PDF columns into an Excel workbook",
    response_description="An .xlsx workbook with extracted values in the requested columns.",
)
async def export_custom_pdf(
    file: Annotated[UploadFile, File(description="Source PDF")],
    mappings: Annotated[str, Form(description="JSON array of selected heading mappings")],
    ocr_pages: Annotated[str, Form(description="Optional JSON array of OCR words for scanned pages")] = "[]",
    current_user: User = Depends(get_current_user),
):
    """Accept mappings with pageNumber, text, header, column, and normalized bbox.

    For scanned pages, pass OCR output as ocr_pages with each page's pixel
    width/height and words containing text plus pixel-coordinate bbox values.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="A PDF filename is required.")

    try:
        file_bytes = await file.read()
        validate_pdf_upload(file, file_bytes)
    except FileValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        mappings_data = json.loads(mappings)
        ocr_data = json.loads(ocr_pages)
        if not isinstance(mappings_data, list) or not mappings_data:
            raise ValueError("At least one mapping is required.")
        if len(mappings_data) > 26:
            raise ValueError("A maximum of 26 mappings is supported.")
        if not isinstance(ocr_data, list):
            raise ValueError("OCR pages must be a JSON array.")

        selections = [MappingSelection.model_validate(item) for item in mappings_data]
        parsed_ocr_pages = [OcrPage.model_validate(item) for item in ocr_data]
        columns = [selection.column for selection in selections]
        if len(columns) != len(set(columns)):
            raise ValueError("Each mapping must use a different Excel column.")
    except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid custom extraction request: {exc}") from exc

    try:
        output = build_custom_workbook(file_bytes, selections, parsed_ocr_pages)
    except CustomExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename).stem).strip("._") or "custom-extraction"
    logger.info(
        "Custom PDF extraction completed: user_id=%s filename=%s mapping_count=%s",
        current_user.id,
        file.filename,
        len(selections),
    )
    return StreamingResponse(
        iter([output]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_stem}.xlsx"'},
    )