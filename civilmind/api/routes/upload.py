"""File upload endpoint."""

import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from civilmind.config import SUPPORTED_FORMATS
from civilmind.events.bus import STREAM_INGESTION, EventBus

logger = structlog.get_logger()

router = APIRouter(tags=["upload"])

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
UPLOAD_DIR = Path("uploads")


async def get_event_bus(request) -> EventBus:
    return request.app.state.event_bus


@router.post("/upload", status_code=202)
async def upload_file(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    bus: EventBus = Depends(get_event_bus),
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

    await bus.publish(
        STREAM_INGESTION,
        {
            "event_type": "document.uploaded",
            "document_id": doc_id,
            "project_id": project_id,
            "file_path": str(file_path),
            "filename": file.filename,
        },
    )

    return {
        "document_id": doc_id,
        "filename": file.filename,
        "file_type": suffix,
        "file_size": len(contents),
        "storage_path": str(file_path),
        "status": "processing",
    }
