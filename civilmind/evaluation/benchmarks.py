"""Benchmark runner — automated evaluation against test datasets.

Runs retrieval + generation evaluation, aggregates metrics, and produces reports.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from civilmind.evaluation.cost_tracker import CostTracker
from civilmind.evaluation.faithfulness import FaithfulnessChecker
from civilmind.evaluation.metrics import RetrievalMetrics

logger = structlog.get_logger()


@dataclass
class BenchmarkCase:
    """A single benchmark test case."""

    query: str = ""
    relevant_ids: set[str] = field(default_factory=set)
    context: str = ""  # ground truth context for faithfulness check
    expected_answer: str = ""  # optional expected answer
    tags: list[str] = field(default_factory=list)


@dataclass
class BenchmarkResult:
    """Results from a single benchmark case."""

    query: str = ""
    retrieval_metrics: dict[str, float] = field(default_factory=dict)
    faithfulness: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    passed: bool = True


@dataclass
class BenchmarkReport:
    """Aggregated benchmark report."""

    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    avg_retrieval: dict[str, float] = field(default_factory=dict)
    avg_faithfulness: dict[str, float] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    case_results: list[BenchmarkResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def pass_rate(self) -> float:
        """Fraction of cases that passed."""
        return self.passed_cases / self.total_cases if self.total_cases > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON export."""
        return {
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "pass_rate": round(self.pass_rate, 3),
            "avg_retrieval": self.avg_retrieval,
            "avg_faithfulness": self.avg_faithfulness,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_latency_ms": round(self.total_latency_ms, 1),
            "duration_seconds": round(self.duration_seconds, 1),
        }


class BenchmarkRunner:
    """Run evaluation benchmarks against a retrieval + generation pipeline.

    Usage:
        runner = BenchmarkRunner(
            retriever=hybrid_retriever,
            faithfulness_checker=checker,
        )
        cases = load_cases("benchmarks.json")
        report = await runner.run(cases)
        runner.save_report(report, "report.json")
    """

    def __init__(
        self,
        retriever: Any = None,
        faithfulness_checker: FaithfulnessChecker | None = None,
        retrieval_metrics: RetrievalMetrics | None = None,
        cost_tracker: CostTracker | None = None,
        faithfulness_threshold: float = 0.7,
    ) -> None:
        """Initialize benchmark runner.

        Args:
            retriever: Must have async retrieve(query, project_id) returning list[RetrievedChunk].
            faithfulness_checker: LLM-as-judge checker (optional).
            retrieval_metrics: Custom metrics calculator (default: k=5).
            cost_tracker: Cost tracker instance (optional).
            faithfulness_threshold: Minimum faithfulness to pass.
        """
        self._retriever = retriever
        self._faith_checker = faithfulness_checker
        self._metrics = retrieval_metrics or RetrievalMetrics(k=5)
        self._costs = cost_tracker or CostTracker()
        self._threshold = faithfulness_threshold

    async def run(
        self,
        cases: list[BenchmarkCase],
        project_id: str = "benchmark",
    ) -> BenchmarkReport:
        """Run all benchmark cases and produce a report.

        Args:
            cases: List of BenchmarkCase with queries and ground truth.
            project_id: Project context for retrieval.

        Returns:
            BenchmarkReport with aggregated metrics.
        """
        start = time.monotonic()
        results: list[BenchmarkResult] = []

        for i, case in enumerate(cases):
            logger.info(
                "Running benchmark case",
                index=i + 1,
                total=len(cases),
                query=case.query[:80],
            )
            result = await self._run_case(case, project_id)
            results.append(result)

        duration = time.monotonic() - start

        report = BenchmarkReport(
            total_cases=len(cases),
            passed_cases=sum(1 for r in results if r.passed),
            failed_cases=sum(1 for r in results if not r.passed),
            avg_retrieval=_avg_dicts([r.retrieval_metrics for r in results if r.retrieval_metrics]),
            avg_faithfulness=_avg_dicts([r.faithfulness for r in results if r.faithfulness]),
            total_cost_usd=self._costs.total_cost,
            total_latency_ms=sum(r.latency_ms for r in results),
            case_results=results,
            duration_seconds=duration,
        )

        logger.info(
            "Benchmark complete",
            total=report.total_cases,
            passed=report.passed_cases,
            failed=report.failed_cases,
            pass_rate=round(report.pass_rate, 3),
            duration=round(duration, 1),
        )

        return report

    async def _run_case(
        self,
        case: BenchmarkCase,
        project_id: str,
    ) -> BenchmarkResult:
        """Run a single benchmark case."""
        start = time.monotonic()

        # Retrieve
        retrieved_ids: list[str] = []
        answer = ""
        if self._retriever:
            chunks = await self._retriever.retrieve(
                query=case.query,
                project_id=project_id,
            )
            retrieved_ids = [c.id for c in chunks]
            context_text = "\n\n".join(c.content for c in chunks)
        else:
            context_text = case.context

        # Retrieval metrics
        retrieval_eval = self._metrics.evaluate(
            [
                {
                    "retrieved_ids": retrieved_ids,
                    "relevant_ids": case.relevant_ids,
                }
            ]
        )
        retrieval_dict = retrieval_eval.summary

        # Faithfulness
        faith_dict: dict[str, Any] = {}
        if self._faith_checker and answer:
            faith_result = await self._faith_checker.evaluate(
                query=case.query,
                context=context_text,
                answer=answer,
            )
            faith_dict = faith_result.summary

        elapsed = (time.monotonic() - start) * 1000
        passed = retrieval_dict.get("recall_at_k", 0) >= 0.5

        return BenchmarkResult(
            query=case.query,
            retrieval_metrics=retrieval_dict,
            faithfulness=faith_dict,
            latency_ms=elapsed,
            cost_usd=0.0,
            passed=passed,
        )

    @staticmethod
    def load_cases(path: str | Path) -> list[BenchmarkCase]:
        """Load benchmark cases from a JSON file.

        Expected format:
        [
            {
                "query": "What concrete grade is used?",
                "relevant_ids": ["chunk-1", "chunk-2"],
                "context": "...",
                "expected_answer": "...",
                "tags": ["structural", "concrete"]
            }
        ]
        """
        with open(path) as f:
            data = json.load(f)

        return [
            BenchmarkCase(
                query=item["query"],
                relevant_ids=set(item.get("relevant_ids", [])),
                context=item.get("context", ""),
                expected_answer=item.get("expected_answer", ""),
                tags=item.get("tags", []),
            )
            for item in data
        ]

    @staticmethod
    def save_report(
        report: BenchmarkReport,
        path: str | Path,
    ) -> None:
        """Save benchmark report to JSON."""
        with open(path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        logger.info("Benchmark report saved", path=str(path))


def _avg_dicts(dicts: list[dict[str, float]]) -> dict[str, float]:
    """Average numeric values across a list of dicts."""
    if not dicts:
        return {}
    keys = dicts[0].keys()
    return {k: sum(d.get(k, 0.0) for d in dicts) / len(dicts) for k in keys}
