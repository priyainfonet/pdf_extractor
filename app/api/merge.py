"""
Merge PDF API

POST /api/merge
    Accepts multiple PDF files and returns one merged PDF.

The endpoint requires an authenticated user.
"""

import io
import logging
from typing import List

from fastapi import APIRouter, UploadFile, File as FastAPIFile
from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse

from pypdf import PdfReader, PdfWriter

from app.core.deps import get_current_user
from app.models.user import User
from app.utils.file_validation import validate_pdf_upload, FileValidationError


router = APIRouter(
    prefix="/api/merge",
    tags=["merge"],
)

logger = logging.getLogger("merge_api")


@router.post("")
async def merge_pdfs(
    files: List[UploadFile] = FastAPIFile(...),
    current_user: User = Depends(get_current_user),
):
    """
    Merge multiple PDF files into a single PDF.

    The order of PDFs in the multipart request is preserved.
    """

    # ---------------------------------------------------------
    # 1. Basic validation
    # ---------------------------------------------------------

    if not files:
        raise HTTPException(
            status_code=400,
            detail="Please select at least two PDF files.",
        )

    if len(files) < 2:
        raise HTTPException(
            status_code=400,
            detail="At least two PDF files are required for merging.",
        )

    logger.info(
        "PDF merge started: user_id=%s file_count=%s",
        current_user.id,
        len(files),
    )

    writer = PdfWriter()

    try:
        # -----------------------------------------------------
        # 2. Process PDFs in the order received
        # -----------------------------------------------------

        for upload in files:

            if not upload.filename:
                raise HTTPException(
                    status_code=400,
                    detail="One of the uploaded files has no filename.",
                )

            # Read uploaded PDF
            file_bytes = await upload.read()

            # Validate using your existing PDF validation
            try:
                validate_pdf_upload(upload, file_bytes)
            except FileValidationError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"{upload.filename}: {exc}",
                )

            # Make sure the uploaded content is actually readable
            try:
                pdf_stream = io.BytesIO(file_bytes)
                reader = PdfReader(pdf_stream)

                if len(reader.pages) == 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{upload.filename} does not contain any pages.",
                    )

                # Add this PDF's pages to the output
                writer.append(reader)

            except HTTPException:
                raise

            except Exception as exc:
                logger.exception(
                    "Unable to read PDF: filename=%s user_id=%s",
                    upload.filename,
                    current_user.id,
                )

                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to read PDF '{upload.filename}': {exc}",
                )

        # -----------------------------------------------------
        # 3. Create merged PDF in memory
        # -----------------------------------------------------

        output_stream = io.BytesIO()

        writer.write(output_stream)

        output_stream.seek(0)

        logger.info(
            "PDF merge completed: user_id=%s file_count=%s",
            current_user.id,
            len(files),
        )

        # -----------------------------------------------------
        # 4. Return merged PDF
        # -----------------------------------------------------

        return StreamingResponse(
            output_stream,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="merged.pdf"'
            },
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "PDF merge failed: user_id=%s",
            current_user.id,
        )

        raise HTTPException(
            status_code=500,
            detail=f"Failed to merge PDFs: {exc}",
        )

    finally:
        writer.close()