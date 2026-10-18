"""HTTP-level tests for the native database service."""

from __future__ import annotations

from fastapi.testclient import TestClient

from civilmind.native_db.server import create_app
from civilmind.native_db.store import NativeStore


def test_put_search_and_delete_api(tmp_path) -> None:
    store = NativeStore(tmp_path)
    app = create_app(store=store, api_token="test-secret")
    with TestClient(app) as client:
        rejected = client.put("/v1/chunks", json={"id": "c1", "project_id": "p1",
            "document_id": "d1", "revision_id": "r1", "content": "IS 456 concrete column detail"})
        assert rejected.status_code == 401
        headers = {"Authorization": "Bearer test-secret"}
        inserted = client.put("/v1/chunks", headers=headers, json={"id": "c1", "project_id": "p1",
            "document_id": "d1", "revision_id": "r1", "content": "IS 456 concrete column detail",
            "metadata": {"discipline": "structural"}, "vector": [1.0, 0.0]})
        assert inserted.status_code == 200
        assert inserted.json()["status"] == "committed"
        result = client.post("/v1/search", headers=headers, json={"query": "IS 456", "project_id": "p1",
            "query_vector": [1.0, 0.0], "metadata_filter": {"discipline": "structural"}})
        assert result.status_code == 200
        assert result.json()["count"] == 1
        assert result.json()["results"][0]["id"] == "c1"
        deleted = client.delete("/v1/chunks/c1", headers=headers)
        assert deleted.status_code == 200
        assert store.count == 0
