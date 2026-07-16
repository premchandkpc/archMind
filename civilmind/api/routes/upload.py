"""File upload endpoint."""

import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from civilmind.config import SUPPORTED_FORMATS

logger = structlog.get_logger()

router = APIRouter(tags=["upload"])

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
UPLOAD_DIR = Path("uploads")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    project_id: str = Form(...),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        supported = ", ".join(SUPPORTED_FORMATS.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: {supported}",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Max size: 100MB")

    doc_id = str(uuid.uuid4())
    storage_path = f"projects/{project_id}/docs/{doc_id}{suffix}"

    project_dir = UPLOAD_DIR / project_id / "docs"
    project_dir.mkdir(parents=True, exist_ok=True)
    file_path = project_dir / f"{doc_id}{suffix}"
    file_path.write_bytes(contents)

    logger.info(
        "File uploaded",
        document_id=doc_id,
        filename=file.filename,
        file_type=suffix,
        file_size=len(contents),
        project_id=project_id,
    )

    return {
        "document_id": doc_id,
        "filename": file.filename,
        "file_type": suffix,
        "file_size": len(contents),
        "storage_path": storage_path,
    }
