"""API boundary tests for PDF drawing inspection."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

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
