"""Qdrant vector store wrapper — project-specific operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from qdrant_client import QdrantClient, models
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from civilmind.config import VECTOR_TOP_K

logger = structlog.get_logger()


@dataclass
class SearchResult:
    id: str
    score: float
    payload: dict
    vector: list[float] | None = None


class QdrantStore:
    """Async-safe Qdrant wrapper with project-specific operations."""

    def __init__(self, url: str, api_key: str | None = None) -> None:
        self._client = QdrantClient(url=url, api_key=api_key, timeout=30)
        self._url = url

    async def create_collection(
        self, name: str, dim: int = 768, recreate: bool = False
    ) -> None:
        """Create collection with cosine distance. Idempotent."""
        existing = [c.name for c in self._client.get_collections().collections]

        if name in existing:
            if recreate:
                logger.warning("Recreating collection", collection=name)
                self._client.delete_collection(name)
            else:
                logger.debug("Collection exists", collection=name)
                return

        self._client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        logger.info("Created collection", collection=name, dim=dim)

    async def delete_collection(self, name: str) -> None:
        """Delete collection entirely."""
        self._client.delete_collection(name)
        logger.info("Deleted collection", collection=name)

    async def upsert(
        self,
        collection: str,
        vectors: list[list[float]],
        payloads: list[dict],
        ids: list[str] | None = None,
    ) -> list[str]:
        """Upsert points. Returns point IDs (for embedding_id in Chunk model)."""
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in vectors]

        points = [
            PointStruct(id=pid, vector=vec, payload=payload)
            for pid, vec, payload in zip(ids, vectors, payloads)
        ]

        self._client.upsert(collection_name=collection, points=points)
        logger.debug("Upserted points", collection=collection, count=len(points))
        return ids

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        filter_dict: dict[str, str] | None = None,
        limit: int = VECTOR_TOP_K,
    ) -> list[SearchResult]:
        """Vector search with optional metadata filters."""
        search_filter = self._build_filter(filter_dict)

        results = self._client.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=search_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        return [
            SearchResult(
                id=str(hit.id),
                score=hit.score,
                payload=hit.payload or {},
            )
            for hit in results
        ]

    async def search_batch(
        self,
        collection: str,
        query_vectors: list[list[float]],
        filter_dict: dict[str, str] | None = None,
        limit: int = VECTOR_TOP_K,
    ) -> list[list[SearchResult]]:
        """Batch search — multiple queries in one round-trip."""
        search_filter = self._build_filter(filter_dict)

        results = self._client.search_batch(
            collection_name=collection,
            requests=[
                models.SearchRequest(
                    vector=qv,
                    filter=search_filter,
                    limit=limit,
                    with_payload=True,
                    with_vectors=False,
                )
                for qv in query_vectors
            ],
        )

        return [
            [
                SearchResult(
                    id=str(hit.id),
                    score=hit.score,
                    payload=hit.payload or {},
                )
                for hit in batch
            ]
            for batch in results
        ]

    async def delete_by_filter(
        self, collection: str, filter_dict: dict[str, str]
    ) -> None:
        """Delete all points matching filter."""
        search_filter = self._build_filter(filter_dict)
        self._client.delete(
            collection_name=collection,
            points_selector=models.FilterSelector(filter=search_filter),
        )
        logger.debug("Deleted by filter", collection=collection, filter=filter_dict)

    async def delete_by_ids(self, collection: str, ids: list[str]) -> None:
        """Delete specific points by ID."""
        self._client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(points=ids),
        )
        logger.debug("Deleted by IDs", collection=collection, count=len(ids))

    async def get_collection_info(self, collection: str) -> dict:
        """Return collection metadata (vector count, config, etc.)."""
        info = self._client.get_collection(collection)
        return {
            "name": collection,
            "points_count": info.points_count,
            "indexed_vectors_count": info.indexed_vectors_count,
            "segments_count": info.segments_count,
            "status": info.status.name if info.status else "unknown",
            "optimizer_status": info.optimizer_status.name
            if info.optimizer_status
            else "unknown",
        }

    async def scroll(
        self,
        collection: str,
        filter_dict: dict[str, str] | None = None,
        limit: int = 100,
        offset: str | None = None,
    ) -> tuple[list[dict], str | None]:
        """Paginated iteration through all points with filter."""
        search_filter = self._build_filter(filter_dict)

        next_offset = models.PointIdFactory(uuid=offset) if offset else None

        points, next_page_offset = self._client.scroll(
            collection_name=collection,
            scroll_filter=search_filter,
            limit=limit,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )

        result = [
            {
                "id": str(p.id),
                "payload": p.payload or {},
            }
            for p in points
        ]

        new_offset = str(next_page_offset.uuid) if next_page_offset else None
        return result, new_offset

    async def health_check(self) -> bool:
        """Check Qdrant connectivity."""
        try:
            self._client.get_collections()
            return True
        except Exception:
            return False

    def close(self) -> None:
        """Close the underlying client."""
        self._client.close()

    @staticmethod
    def _build_filter(filter_dict: dict[str, str] | None) -> Filter | None:
        """Convert simple dict filter to Qdrant Filter object."""
        if not filter_dict:
            return None

        conditions = [
            FieldCondition(key=key, match=MatchValue(value=value))
            for key, value in filter_dict.items()
        ]
        return Filter(must=conditions)
