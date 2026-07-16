"""HybridRetriever — orchestrates BM25 + vector + RRF + rerank + compress.

The full retrieval pipeline:
  1. BM25 keyword search (top 20)
  2. Vector semantic search (top 20)
  3. Reciprocal Rank Fusion merge (top 30)
  4. Cross-encoder rerank (top 10)
  5. Context compression (top 5)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from civilmind.config import (
    BM25_TOP_K,
    FINAL_TOP_K,
    MIN_CORPUS_FOR_BM25,
    RERANK_TOP_K,
    RRF_MERGE_TOP_K,
    VECTOR_TOP_K,
)
from civilmind.retrieval.bm25_index import BM25Index, BM25Result
from civilmind.retrieval.compressor import ContextCompressor
from civilmind.retrieval.reranker import CrossEncoderReranker

if TYPE_CHECKING:
    from civilmind.pipeline.embedder import BaseEmbedder
    from civilmind.vector.qdrant_store import QdrantStore, SearchResult

logger = structlog.get_logger()


@dataclass
class RetrievedChunk:
    id: str
    content: str
    score: float
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    retrieval_method: str = "hybrid"


class HybridRetriever:
    """Orchestrate BM25 + vector search with RRF merge + reranking."""

    def __init__(
        self,
        qdrant: QdrantStore,
        bm25_index: BM25Index,
        embedder: BaseEmbedder,
        reranker: CrossEncoderReranker | None = None,
        compressor: ContextCompressor | None = None,
    ) -> None:
        self._qdrant = qdrant
        self._bm25 = bm25_index
        self._embedder = embedder
        self._reranker = reranker or CrossEncoderReranker()
        self._compressor = compressor or ContextCompressor()

    async def retrieve(
        self,
        query: str,
        project_id: str,
        metadata_filter: dict[str, str] | None = None,
        top_k: int = FINAL_TOP_K,
    ) -> list[RetrievedChunk]:
        """Full hybrid retrieval pipeline.

        Args:
            query: Natural language query (e.g. "concrete grade for foundations").
            project_id: Filter by project.
            metadata_filter: Optional additional filters (e.g. {"doc_type": "structural"}).
            top_k: Number of final results.

        Returns:
            List of RetrievedChunk with compressed, reranked content.
        """
        start = time.monotonic()

        # Step 1: Embed query for vector search
        query_vector = await self._embedder.embed(query)

        # Step 2: Run BM25 + vector in parallel
        bm25_results, vector_results = await asyncio.gather(
            self._run_bm25(query, project_id),
            self._run_vector(query_vector, project_id, metadata_filter),
        )

        # Step 3: RRF merge
        merged = self._rrf_merge(vector_results, bm25_results, k=60)

        # Step 4: Cross-encoder rerank
        reranked = self._reranker.rerank(query, merged, top_k=RERANK_TOP_K)

        # Step 5: Context compression
        compressed = []
        for r in reranked[:top_k]:
            compressed_content = self._compressor.compress(query, r.content)
            compressed.append(
                RetrievedChunk(
                    id=r.id,
                    content=compressed_content,
                    score=r.score,
                    source=r.metadata.get("document_id", "unknown"),
                    metadata=r.metadata,
                    retrieval_method="hybrid",
                )
            )

        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "Hybrid retrieval complete",
            elapsed_ms=round(elapsed, 1),
            results=len(compressed),
        )

        return compressed

    async def _run_bm25(self, query: str, project_id: str) -> list[BM25Result]:
        if self._bm25.size < MIN_CORPUS_FOR_BM25:
            return []
        return self._bm25.search(query, top_k=BM25_TOP_K)

    async def _run_vector(
        self,
        query_vector: list[float],
        project_id: str,
        filter_dict: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        combined_filter = dict(filter_dict or {})
        combined_filter["project_id"] = project_id
        return await self._qdrant.search(
            collection="civilmind",
            query_vector=query_vector,
            filter_dict=combined_filter,
            limit=VECTOR_TOP_K,
        )

    @staticmethod
    def _rrf_merge(
        vector_results: list[Any],
        bm25_results: list[Any],
        k: int = 60,
    ) -> list[Any]:
        scores: dict[str, dict[str, Any]] = {}

        for rank, doc in enumerate(vector_results):
            if doc.id not in scores:
                scores[doc.id] = {"doc": doc, "score": 0.0}
            scores[doc.id]["score"] += 1.0 / (k + rank + 1)

        for rank, doc in enumerate(bm25_results):
            if doc.id not in scores:
                scores[doc.id] = {"doc": doc, "score": 0.0}
            scores[doc.id]["score"] += 1.0 / (k + rank + 1)

        merged = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        return [item["doc"] for item in merged[:RRF_MERGE_TOP_K]]
