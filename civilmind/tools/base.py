"""Abstract tool interface and result type.

Agents never query databases directly — they call tools.
Tools are swappable, testable, and independently deployable.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class ToolResult:
    """Standardized result from every tool execution."""

    success: bool
    data: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    tokens_used: int | None = None
    metadata: dict = field(default_factory=dict)


class BaseTool(ABC):
    """Abstract base class for all tools.

    Subclasses must define name, description, category, and implement execute().
    """

    name: str
    description: str
    category: str  # retrieval, calculation, vision, knowledge

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult: ...

    async def __call__(self, **kwargs: Any) -> ToolResult:
        """Allow calling tool like a function. Wraps execute with timing."""
        start = time.monotonic()
        try:
            result = await self.execute(**kwargs)
        except Exception as e:
            logger.error("Tool execution failed", tool=self.name, error=str(e))
            result = ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        else:
            result.latency_ms = (time.monotonic() - start) * 1000
            logger.debug(
                "Tool executed",
                tool=self.name,
                success=result.success,
                latency_ms=round(result.latency_ms, 2),
            )
        return result
