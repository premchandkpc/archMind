"""Evaluation layer — retrieval metrics, faithfulness, cost tracking, benchmarks."""

from __future__ import annotations

from civilmind.evaluation.benchmarks import BenchmarkRunner
from civilmind.evaluation.cost_tracker import CostTracker, QueryCost
from civilmind.evaluation.faithfulness import FaithfulnessChecker, FaithfulnessResult
from civilmind.evaluation.metrics import RetrievalMetricResult, RetrievalMetrics

__all__ = [
    "BenchmarkRunner",
    "CostTracker",
    "FaithfulnessChecker",
    "FaithfulnessResult",
    "QueryCost",
    "RetrievalMetricResult",
    "RetrievalMetrics",
]
