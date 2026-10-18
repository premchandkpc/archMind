"""VectorSearchTool — semantic search via Qdrant.

Agents call this tool, never Qdrant directly.
Returns chunks with scores for downstream reranking.
"""

from __future__ import annotations

from typing import Any

import structlog

from civilmind.config import VECTOR_TOP_K
from civilmind.settings import settings
from civilmind.tools.base import BaseTool, ToolResult
from civilmind.vector.native_db_store import NativeDBClient
from civilmind.vector.qdrant_store import QdrantStore

logger = structlog.get_logger()


class VectorSearchTool(BaseTool):
    """Semantic vector search over project documents in Qdrant."""

    name = "vector_search"
    description = "Search project documents using semantic similarity"
    category = "retrieval"

    def __init__(
        self,
        qdrant: QdrantStore | None = None,
        native_db: NativeDBClient | None = None,
    ) -> None:
        self._native_db: NativeDBClient | None = None
        self._qdrant: QdrantStore | None = None
        if settings.RETRIEVAL_BACKEND == "native_db":
            self._native_db = native_db or NativeDBClient()
        else:
            self._qdrant = qdrant or QdrantStore(url=settings.QDRANT_URL)

    async def execute(
        self,
        query_vector: list[float],
        project_id: str,
        query: str = "",
        top_k: int = VECTOR_TOP_K,
        filter_dict: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Vector search with optional metadata filters.

        Args:
            query_vector: Embedding of the user query.
            project_id: Filter results to this project.
            top_k: Number of results to return.
            filter_dict: Additional metadata filters (merged with project_id).

        Returns:
            ToolResult with list of {id, score, payload} dicts.
        """
        filters = dict(filter_dict or {})
        filters["project_id"] = project_id

        try:
            if self._native_db is not None:
                results = await self._native_db.search(
                    query=query,
                    query_vector=query_vector,
                    project_id=project_id,
                    filter_dict=filters,
                    limit=top_k,
                )
                collection = "native-db"
            else:
                assert self._qdrant is not None
                results = await self._qdrant.search(
                    collection=settings.QDRANT_COLLECTION,
                    query_vector=query_vector,
                    filter_dict=filters,
                    limit=top_k,
                )
                collection = settings.QDRANT_COLLECTION

            data = [{"id": r.id, "score": round(r.score, 4), "payload": r.payload} for r in results]

            logger.info(
                "Vector search completed",
                project_id=project_id,
                top_k=top_k,
                results_count=len(data),
            )

            return ToolResult(
                success=True,
                data=data,
                metadata={"collection": collection, "top_k": top_k},
            )

        except Exception as e:
            logger.error(
                "Vector search failed",
                project_id=project_id,
                error=str(e),
            )
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
            )

    async def health_check(self) -> bool:
        """Check the configured retrieval backend."""
        if self._native_db is not None:
            return await self._native_db.health_check()
        assert self._qdrant is not None
        return await self._qdrant.health_check()
