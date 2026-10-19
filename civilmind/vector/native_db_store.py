"""Async HTTP client for CivilMind's standalone Go retrieval database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import httpx
import structlog

from civilmind.settings import settings

logger = structlog.get_logger()

# Keep batches comfortably below the Go service's 4 MiB HTTP body limit.
DEFAULT_BATCH_SIZE = 32


@dataclass(frozen=True, slots=True)
class NativeSearchResult:
    """Result normalized to the same shape used by the Qdrant adapter."""

    id: str
    score: float
    payload: dict[str, Any]


class NativeDBClient:
    """Client for batched ingestion and hybrid retrieval via the Go engine.

    The Go service owns persistence, lexical indexing, vector search, and RRF.
    CivilMind remains responsible for parsing documents and creating embeddings.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.AsyncClient | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._base_url = (base_url or settings.CIVILMIND_DB_URL).rstrip("/")
        self._token = settings.CIVILMIND_DB_TOKEN if token is None else token
        timeout = timeout_seconds or settings.CIVILMIND_DB_TIMEOUT_SECONDS
        if not self._token.strip():
            raise ValueError("CIVILMIND_DB_TOKEN is required for the native database client")
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        if batch_size < 1 or batch_size > 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        self._batch_size = batch_size
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def upsert_chunks(
        self,
        chunks: Sequence[dict[str, Any]],
        vectors: Sequence[list[float]],
    ) -> list[str]:
        """Atomically persist chunk batches and return their stable IDs.

        Args:
            chunks: Parsed CivilMind chunks with id, content and metadata.
            vectors: Embeddings in the same order as chunks.

        Returns:
            Chunk IDs, in input order.
        """
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return []

        ids: list[str] = []
        for start in range(0, len(chunks), self._batch_size):
            chunk_batch = chunks[start : start + self._batch_size]
            vector_batch = vectors[start : start + self._batch_size]
            records: list[dict[str, Any]] = []
            for index, (raw_chunk, vector) in enumerate(zip(chunk_batch, vector_batch), start=start):
                metadata_value = raw_chunk.get("metadata") or {}
                if not isinstance(metadata_value, dict):
                    raise ValueError(f"chunks[{index}].metadata must be an object")
                metadata = dict(metadata_value)
                chunk_id = str(raw_chunk.get("id") or "")
                content = str(raw_chunk.get("content") or "")
                project_id = str(metadata.get("project_id") or raw_chunk.get("project_id") or "")
                document_id = str(metadata.get("document_id") or raw_chunk.get("document_id") or "")
                # Current CivilMind uploads create one document ID per uploaded revision.
                revision_id = str(
                    metadata.get("revision_id")
                    or metadata.get("version")
                    or raw_chunk.get("revision_id")
                    or document_id
                )
                if not chunk_id or not content or not project_id or not document_id or not revision_id:
                    raise ValueError(
                        f"chunks[{index}] requires id, content, project_id and document_id metadata"
                    )
                records.append(
                    {
                        "id": chunk_id,
                        "project_id": project_id,
                        "document_id": document_id,
                        "revision_id": revision_id,
                        "content": content,
                        "metadata": metadata,
                        "vector": vector,
                    }
                )

            response = await self._request_json(
                "PUT", "/v1/chunks/batch", {"chunks": records}
            )
            returned_ids = response.get("ids")
            if (
                not isinstance(returned_ids, list)
                or len(returned_ids) != len(records)
                or not all(isinstance(value, str) for value in returned_ids)
            ):
                raise RuntimeError("native database returned an invalid batch response")
            ids.extend(returned_ids)

        logger.info("Native DB chunks committed", count=len(ids), batches=(len(ids) + self._batch_size - 1) // self._batch_size)
        return ids

    async def search(
        self,
        query_vector: list[float],
        project_id: str,
        filter_dict: dict[str, Any] | None = None,
        limit: int = 10,
        query: str = "",
    ) -> list[NativeSearchResult]:
        """Run semantic or hybrid lexical/vector search."""
        filters = dict(filter_dict or {})
        filters.pop("project_id", None)
        response = await self._request_json(
            "POST",
            "/v1/search",
            {
                "query": query,
                "project_id": project_id,
                "metadata_filter": filters,
                "query_vector": query_vector,
                "limit": limit,
            },
        )
        raw_results = response.get("results")
        if not isinstance(raw_results, list):
            raise RuntimeError("native database returned an invalid search response")

        results: list[NativeSearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            chunk = item.get("chunk")
            if not isinstance(chunk, dict):
                continue
            chunk_id = chunk.get("id")
            score = item.get("score")
            if not isinstance(chunk_id, str) or not isinstance(score, (int, float)):
                continue
            metadata = chunk.get("metadata")
            payload = dict(metadata) if isinstance(metadata, dict) else {}
            payload.update(
                {
                    "content": chunk.get("content", ""),
                    "project_id": chunk.get("project_id", project_id),
                    "document_id": chunk.get("document_id", ""),
                    "revision_id": chunk.get("revision_id", ""),
                }
            )
            results.append(
                NativeSearchResult(id=chunk_id, score=float(score), payload=payload)
            )
        return results

    async def delete_chunk(self, chunk_id: str) -> None:
        """Delete one chunk from the native database."""
        await self._request_json("DELETE", f"/v1/chunks/{chunk_id}")

    async def health_check(self) -> bool:
        """Return whether the native database's liveness endpoint responds."""
        try:
            response = await self._client.get(f"{self._base_url}/health")
            response.raise_for_status()
            return response.json().get("status") == "ok"
        except Exception as exc:
            logger.warning("Native DB health check failed", error=str(exc))
            return False

    async def close(self) -> None:
        """Close the underlying HTTP session if this client created it."""
        if self._owns_client:
            await self._client.aclose()

    async def _request_json(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await self._client.request(
            method,
            f"{self._base_url}{path}",
            headers={"Authorization": f"Bearer {self._token}"},
            json=payload,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("native database response must be a JSON object")
        return result
