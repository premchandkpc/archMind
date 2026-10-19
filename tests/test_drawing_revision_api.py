"""API boundary tests for PDF drawing inspection."""

import threading
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from starlette.datastructures import UploadFile as StarletteUploadFile

import civilmind.api.routes.drawing_revisions as drawing_revisions
from civilmind.api.routes.drawing_revisions import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_inspect_rejects_non_pdf_extension() -> None:
    response = client().post(
        "/drawing-revisions/inspect",
        files={"file": ("drawing.dwg", b"not a PDF", "application/octet-stream")},
    )

    assert response.status_code == 415


def test_inspect_rejects_invalid_pdf_bytes() -> None:
    response = client().post(
        "/drawing-revisions/inspect",
        files={"file": ("drawing.pdf", b"not a PDF", "application/pdf")},
    )

    assert response.status_code == 422



@pytest.mark.asyncio
async def test_pdf_parsing_runs_off_the_event_loop_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    event_loop_thread = threading.get_ident()
    parser_threads: list[int] = []

    def fake_parser(contents: bytes, filename: str) -> dict[str, object]:
        parser_threads.append(threading.get_ident())
        return {"filename": filename, "file_size_bytes": len(contents), "pages": []}

    monkeypatch.setattr(drawing_revisions, "_inspect_pdf_contents", fake_parser)
    upload = StarletteUploadFile(
        file=BytesIO(b"%PDF-1.7 test bytes"),
        filename="sample.pdf",
    )

    result = await drawing_revisions.inspect_drawing_pdf(upload)

    assert result["filename"] == "sample.pdf"
    assert parser_threads
    assert parser_threads[0] != event_loop_thread
