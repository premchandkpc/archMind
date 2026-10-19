"""PDF-first drawing revision inspection endpoints."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from civilmind.drawing_control.title_block import parse_title_block_text

router = APIRouter(prefix="/drawing-revisions", tags=["drawing-revisions"])

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 200


def _inspect_pdf_contents(contents: bytes, filename: str) -> dict[str, object]:
    """Perform synchronous PDF parsing in a worker thread, not the event loop."""
    try:
        reader = PdfReader(BytesIO(contents), strict=False)
        if reader.is_encrypted:
            raise HTTPException(status_code=422, detail="Encrypted PDFs are not supported.")
        page_count = len(reader.pages)
        if page_count == 0:
            raise HTTPException(status_code=422, detail="PDF contains no pages.")
        if page_count > MAX_PDF_PAGES:
            raise HTTPException(
                status_code=413,
                detail=f"PDF has {page_count} pages; limit is {MAX_PDF_PAGES}.",
            )
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            extracted = page.extract_text() or ""
            result = parse_title_block_text(extracted)
            pages.append({"page_number": index, **result.to_dict()})
    except HTTPException:
        raise
    except (PdfReadError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Could not read the PDF file.") from exc

    matched = sum(page["status"] == "matched" for page in pages)
    return {
        "filename": filename,
        "file_size_bytes": len(contents),
        "sha256": hashlib.sha256(contents).hexdigest(),
        "page_count": page_count,
        "matched_pages": matched,
        "unmatched_pages": page_count - matched,
        "pages": pages,
        "limitations": [
            "Text extraction only; scanned pages require OCR and are returned as unmatched.",
            "Title-block parsing is a candidate, not a verified sheet identity.",
            "This endpoint does not persist revisions or modify source design files.",
        ],
    }


@router.post("/inspect")
async def inspect_drawing_pdf(file: UploadFile = File(...)) -> dict[str, object]:
    """Extract title-block candidates from a PDF without silently assigning identity."""
    filename = Path(file.filename or "drawing.pdf").name
    if Path(filename).suffix.casefold() != ".pdf":
        raise HTTPException(status_code=415, detail="Only PDF drawing files are supported.")

    contents = await file.read(MAX_PDF_BYTES + 1)
    if len(contents) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds the 25 MiB upload limit.")
    if not contents.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="The uploaded file is not a valid PDF.")

    return await run_in_threadpool(_inspect_pdf_contents, contents, filename)
