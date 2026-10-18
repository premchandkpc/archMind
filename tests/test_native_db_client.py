"""Tests for the Python client that connects CivilMind to the Go database."""

from __future__ import annotations

import json

import httpx
import pytest

from civilmind.vector.native_db_store import NativeDBClient


@pytest.mark.asyncio
async def test_upsert_chunks_batches_and_returns_stable_ids() -> None:
    requests: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.url.path == "/v1/chunks/batch"
        body = json.loads(request.content)
        requests.append(body)
        chunks = body["chunks"]
        return httpx.Response(200, json={"ids": [chunk["id"] for chunk in chunks]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = NativeDBClient(
            base_url="http://native-db.test",
            token="test-token",
            client=http_client,
            batch_size=1,
        )
        chunks = [
            {
                "id": "c1",
                "content": "Column C12 width 450 mm",
                "metadata": {"project_id": "p1", "document_id": "S101"},
            },
            {
                "id": "c2",
                "content": "Pipe clearance near C12",
                "metadata": {"project_id": "p1", "document_id": "M301"},
            },
        ]
        ids = await client.upsert_chunks(chunks, [[1.0, 0.0], [0.0, 1.0]])

    assert ids == ["c1", "c2"]
    assert len(requests) == 2
    assert requests[0]["chunks"][0]["revision_id"] == "S101"
    assert requests[1]["chunks"][0]["vector"] == [0.0, 1.0]


@pytest.mark.asyncio
async def test_hybrid_search_normalizes_native_db_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        assert body["project_id"] == "p1"
        assert body["metadata_filter"] == {"discipline": "structural"}
        assert body["query"] == "column width"
        return httpx.Response(
            200,
            json={
                "count": 1,
                "sequence": 3,
                "results": [
                    {
                        "chunk": {
                            "id": "c1",
                            "project_id": "p1",
                            "document_id": "S101",
                            "revision_id": "R2",
                            "content": "Column C12 width 600 mm",
                            "metadata": {"discipline": "structural"},
                        },
                        "score": 0.032,
                        "lexical_score": 1.2,
                        "vector_score": 0.98,
                        "lexical_rank": 1,
                        "vector_rank": 1,
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = NativeDBClient(
            base_url="http://native-db.test",
            token="test-token",
            client=http_client,
        )
        results = await client.search(
            query="column width",
            query_vector=[1.0, 0.0],
            project_id="p1",
            filter_dict={"project_id": "p1", "discipline": "structural"},
            limit=5,
        )

    assert len(results) == 1
    assert results[0].id == "c1"
    assert results[0].payload["content"] == "Column C12 width 600 mm"
    assert results[0].payload["revision_id"] == "R2"


@pytest.mark.asyncio
async def test_upsert_rejects_mismatched_chunk_and_vector_counts() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as http_client:
        client = NativeDBClient(base_url="http://native-db.test", token="secret", client=http_client)
        with pytest.raises(ValueError, match="same length"):
            await client.upsert_chunks([{"id": "c1"}], [])


def test_native_client_requires_token() -> None:
    with pytest.raises(ValueError, match="CIVILMIND_DB_TOKEN"):
        NativeDBClient(base_url="http://native-db.test", token="")
