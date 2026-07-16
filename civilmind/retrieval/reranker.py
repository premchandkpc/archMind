"""CrossEncoderReranker — precision relevance ranking.

Takes (query, doc) pairs and computes relevance scores.
Cross-encoder attends to both query and document together,
giving better accuracy than bi-encoder (embedding) similarity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from civilmind.config import RERANK_TOP_K

logger = structlog.get_logger()


@dataclass
class RerankResult:
    id: str
    content: str
    score: float
    original_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class CrossEncoderReranker:
    """Rerank documents using a cross-encoder model."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        self._model_name = model_name
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(self._model_name)
                logger.info("Loaded cross-encoder model", model=self._model_name)
            except ImportError:
                logger.warning("sentence-transformers not installed, reranker disabled")
                return None
        return self._model

    def rerank(
        self,
        query: str,
        documents: list[Any],
        top_k: int = RERANK_TOP_K,
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query.

        Args:
            query: The search query.
            documents: List of objects with .id, .content, .score, .metadata.
            top_k: Number of results to return.

        Returns:
            List of RerankResult sorted by relevance score (highest first).
        """
        model = self._get_model()
        if model is None:
            return [
                RerankResult(
                    id=d.id,
                    content=d.content,
                    score=d.score,
                    original_score=d.score,
                    metadata=d.metadata,
                )
                for d in documents[:top_k]
            ]

        if not documents:
            return []

        pairs = [(query, d.content) for d in documents]
        scores = model.predict(pairs)

        ranked = sorted(
            [
                RerankResult(
                    id=documents[i].id,
                    content=documents[i].content,
                    score=float(scores[i]),
                    original_score=documents[i].score,
                    metadata=documents[i].metadata,
                )
                for i in range(len(documents))
            ],
            key=lambda x: x.score,
            reverse=True,
        )

        return ranked[:top_k]
