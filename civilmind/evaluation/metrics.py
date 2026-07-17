"""Retrieval metrics — Recall@K, Precision@K, MRR, NDCG.

Standard information retrieval metrics for evaluating chunk retrieval
quality against ground truth annotations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class RetrievalMetricResult:
    """Result of a single metric calculation."""

    recall_at_k: float = 0.0
    precision_at_k: float = 0.0
    mrr: float = 0.0
    ndcg_at_k: float = 0.0
    hit_rate: float = 0.0
    total_queries: int = 0
    k: int = 5

    @property
    def summary(self) -> dict[str, float]:
        """Return metrics as a flat dict for logging/storage."""
        return {
            "recall_at_k": self.recall_at_k,
            "precision_at_k": self.precision_at_k,
            "mrr": self.mrr,
            "ndcg_at_k": self.ndcg_at_k,
            "hit_rate": self.hit_rate,
            "total_queries": self.total_queries,
            "k": self.k,
        }


class RetrievalMetrics:
    """Calculate standard IR metrics for retrieval evaluation.

    Usage:
        metrics = RetrievalMetrics(k=5)
        result = metrics.evaluate(queries)
        print(result.summary)
    """

    def __init__(self, k: int = 5) -> None:
        """Initialize with the cutoff K.

        Args:
            k: Cutoff depth for Precision@K, Recall@K, NDCG@K.
        """
        self._k = k

    def evaluate(
        self,
        query_results: list[dict[str, Any]],
    ) -> RetrievalMetricResult:
        """Evaluate retrieval results against ground truth.

        Args:
            query_results: List of dicts, each with:
                - "retrieved_ids": list[str] — ordered retrieved chunk IDs
                - "relevant_ids": set[str] — ground truth relevant chunk IDs

        Returns:
            Aggregated RetrievalMetricResult across all queries.
        """
        if not query_results:
            return RetrievalMetricResult(k=self._k)

        all_recalls: list[float] = []
        all_precisions: list[float] = []
        all_mrrs: list[float] = []
        all_ndcgs: list[float] = []
        all_hits: list[float] = []

        for qr in query_results:
            retrieved = qr.get("retrieved_ids", [])
            relevant = qr.get("relevant_ids", set())

            if not relevant:
                continue

            all_recalls.append(self._recall_at_k(retrieved, relevant))
            all_precisions.append(self._precision_at_k(retrieved, relevant))
            all_mrrs.append(self._mrr(retrieved, relevant))
            all_ndcgs.append(self._ndcg_at_k(retrieved, relevant))
            all_hits.append(1.0 if self._has_hit(retrieved, relevant) else 0.0)

        n = len(query_results)
        result = RetrievalMetricResult(
            recall_at_k=_safe_mean(all_recalls),
            precision_at_k=_safe_mean(all_precisions),
            mrr=_safe_mean(all_mrrs),
            ndcg_at_k=_safe_mean(all_ndcgs),
            hit_rate=_safe_mean(all_hits),
            total_queries=n,
            k=self._k,
        )

        logger.info(
            "Retrieval evaluation complete",
            total_queries=n,
            recall=round(result.recall_at_k, 3),
            precision=round(result.precision_at_k, 3),
            mrr=round(result.mrr, 3),
            ndcg=round(result.ndcg_at_k, 3),
            hit_rate=round(result.hit_rate, 3),
        )

        return result

    def _recall_at_k(self, retrieved: list[str], relevant: set[str]) -> float:
        """Recall@K = |retrieved ∩ relevant| / |relevant|."""
        top_k = set(retrieved[: self._k])
        return len(top_k & relevant) / len(relevant)

    def _precision_at_k(self, retrieved: list[str], relevant: set[str]) -> float:
        """Precision@K = |retrieved ∩ relevant| / K."""
        top_k = retrieved[: self._k]
        return sum(1 for doc_id in top_k if doc_id in relevant) / self._k

    def _mrr(self, retrieved: list[str], relevant: set[str]) -> float:
        """Mean Reciprocal Rank — 1/rank of first relevant result."""
        for rank, doc_id in enumerate(retrieved, start=1):
            if doc_id in relevant:
                return 1.0 / rank
        return 0.0

    def _ndcg_at_k(self, retrieved: list[str], relevant: set[str]) -> float:
        """Normalized Discounted Cumulative Gain at K."""
        dcg = 0.0
        for i, doc_id in enumerate(retrieved[: self._k]):
            if doc_id in relevant:
                dcg += 1.0 / math.log2(i + 2)  # +2 because rank is 1-based, log2(1)=0

        # Ideal DCG: all relevant docs at top
        ideal_count = min(len(relevant), self._k)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))

        return dcg / idcg if idcg > 0 else 0.0

    def _has_hit(self, retrieved: list[str], relevant: set[str]) -> bool:
        """Check if any relevant doc appears in top K."""
        return bool(set(retrieved[: self._k]) & relevant)


def _safe_mean(values: list[float]) -> float:
    """Mean of a list, returning 0.0 if empty."""
    return sum(values) / len(values) if values else 0.0
