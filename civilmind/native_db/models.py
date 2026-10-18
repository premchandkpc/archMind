"""Typed records used by the CivilMind native retrieval database."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Chunk:
    """A searchable, revision-aware document chunk."""

    id: str
    project_id: str
    document_id: str
    revision_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A hybrid-search result with inspectable ranking components."""

    chunk: Chunk
    score: float
    lexical_score: float
    vector_score: float | None
    lexical_rank: int | None
    vector_rank: int | None
