"""Cost tracker — token counting and cost per query.

Tracks LLM usage costs across queries, sessions, and projects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()

# Approximate costs per 1M tokens (USD) — update as pricing changes
DEFAULT_COST_PER_1M_TOKENS: dict[str, float] = {
    "gpt-5": 2.50,
    "gpt-4o": 2.50,
    "gpt-4o-mini": 0.15,
    "claude-sonnet-4-5": 3.00,
    "claude-haiku": 0.80,
    "default": 1.00,
}


@dataclass
class QueryCost:
    """Cost record for a single query or operation."""

    query_id: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    operation: str = ""  # "chat", "vision", "embedding", "judge"
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class CostTracker:
    """Track LLM token usage and costs.

    Usage:
        tracker = CostTracker()
        tracker.record(query_id="q1", model="gpt-5", tokens=1500, operation="chat")
        print(tracker.total_cost)
        print(tracker.by_model())
    """

    def __init__(
        self,
        cost_per_1m: dict[str, float] | None = None,
    ) -> None:
        """Initialize cost tracker.

        Args:
            cost_per_1m: Override cost per 1M tokens by model name.
        """
        self._costs = {**DEFAULT_COST_PER_1M_TOKENS}
        if cost_per_1m:
            self._costs.update(cost_per_1m)
        self._records: list[QueryCost] = []

    def record(
        self,
        query_id: str = "",
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int | None = None,
        latency_ms: float = 0.0,
        operation: str = "",
        **metadata: Any,
    ) -> QueryCost:
        """Record a token usage event.

        Args:
            query_id: Optional query/request identifier.
            model: Model name (used to look up cost rate).
            input_tokens: Input prompt tokens.
            output_tokens: Output completion tokens.
            total_tokens: Total tokens (overrides sum if provided).
            latency_ms: Request latency in milliseconds.
            operation: Operation type (chat, vision, embedding, judge).
            **metadata: Additional metadata to store.

        Returns:
            QueryCost record.
        """
        total = total_tokens or (input_tokens + output_tokens)
        cost_usd = self._calculate_cost(model, total)

        record = QueryCost(
            query_id=query_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            operation=operation,
            metadata=metadata,
        )
        self._records.append(record)

        logger.debug(
            "Cost recorded",
            model=model,
            tokens=total,
            cost_usd=round(cost_usd, 6),
            operation=operation,
        )

        return record

    def record_from_llm_result(
        self,
        query_id: str,
        model: str,
        tokens_used: int | None,
        latency_ms: float = 0.0,
        operation: str = "chat",
    ) -> QueryCost:
        """Record from an LLMResult object's token count.

        Args:
            query_id: Query identifier.
            model: Model name.
            tokens_used: From LLMResult.tokens_used.
            latency_ms: Request latency.
            operation: Operation type.
        """
        return self.record(
            query_id=query_id,
            model=model,
            total_tokens=tokens_used or 0,
            latency_ms=latency_ms,
            operation=operation,
        )

    @property
    def total_cost(self) -> float:
        """Total USD cost across all recorded queries."""
        return sum(r.cost_usd for r in self._records)

    @property
    def total_tokens(self) -> int:
        """Total tokens across all recorded queries."""
        return sum(r.total_tokens for r in self._records)

    @property
    def query_count(self) -> int:
        """Number of recorded queries."""
        return len(self._records)

    @property
    def avg_latency_ms(self) -> float:
        """Average latency across all queries."""
        if not self._records:
            return 0.0
        return sum(r.latency_ms for r in self._records) / len(self._records)

    def by_model(self) -> dict[str, dict[str, Any]]:
        """Aggregate costs grouped by model name."""
        models: dict[str, dict[str, Any]] = {}
        for r in self._records:
            if r.model not in models:
                models[r.model] = {"count": 0, "tokens": 0, "cost_usd": 0.0}
            models[r.model]["count"] += 1
            models[r.model]["tokens"] += r.total_tokens
            models[r.model]["cost_usd"] += r.cost_usd
        return models

    def by_operation(self) -> dict[str, dict[str, Any]]:
        """Aggregate costs grouped by operation type."""
        ops: dict[str, dict[str, Any]] = {}
        for r in self._records:
            op = r.operation or "unknown"
            if op not in ops:
                ops[op] = {"count": 0, "tokens": 0, "cost_usd": 0.0}
            ops[op]["count"] += 1
            ops[op]["tokens"] += r.total_tokens
            ops[op]["cost_usd"] += r.cost_usd
        return ops

    def summary(self) -> dict[str, Any]:
        """Full cost summary."""
        return {
            "total_cost_usd": round(self.total_cost, 6),
            "total_tokens": self.total_tokens,
            "query_count": self.query_count,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "by_model": self.by_model(),
            "by_operation": self.by_operation(),
        }

    def get_records(self, limit: int = 100) -> list[QueryCost]:
        """Get recent cost records."""
        return self._records[-limit:]

    def _calculate_cost(self, model: str, total_tokens: int) -> float:
        """Calculate USD cost from token count and model rate."""
        rate = self._costs.get(model, self._costs["default"])
        return (total_tokens / 1_000_000) * rate
