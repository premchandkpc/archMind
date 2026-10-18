"""In-memory inverted and flat-vector indexes rebuilt from the durable log."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable

from civilmind.native_db.models import Chunk

_TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._/-]*")


def tokenize(text: str) -> list[str]:
    """Normalize searchable technical terms without discarding codes like IS:456."""
    return [token.casefold() for token in _TOKEN_RE.findall(text)]


@dataclass(frozen=True, slots=True)
class LexicalHit:
    chunk_id: str
    score: float


class SearchIndex:
    """BM25 inverted index plus exact flat cosine search for a prototype-scale corpus."""

    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}
        self._terms: dict[str, dict[str, int]] = defaultdict(dict)
        self._lengths: dict[str, int] = {}
        self._avg_length = 0.0
        self._term_freqs: dict[str, Counter[str]] = {}

    def replace_all(self, chunks: Iterable[Chunk]) -> None:
        """Rebuild every derived index from authoritative chunk records."""
        self._chunks.clear()
        self._terms.clear()
        self._lengths.clear()
        self._term_freqs.clear()
        for chunk in chunks:
            self._add(chunk)
        self._refresh_average_length()

    def upsert(self, chunk: Chunk) -> None:
        """Update one chunk's postings, replacing any older version."""
        self.delete(chunk.id)
        self._add(chunk)
        self._refresh_average_length()

    def delete(self, chunk_id: str) -> None:
        """Remove one chunk and all its derived index entries."""
        if self._chunks.pop(chunk_id, None) is None:
            return
        for term in self._term_freqs.pop(chunk_id, {}):
            posting = self._terms[term]
            posting.pop(chunk_id, None)
            if not posting:
                self._terms.pop(term, None)
        self._lengths.pop(chunk_id, None)
        self._refresh_average_length()

    def _add(self, chunk: Chunk) -> None:
        terms = tokenize(chunk.content)
        counts = Counter(terms)
        self._chunks[chunk.id] = chunk
        self._term_freqs[chunk.id] = counts
        self._lengths[chunk.id] = len(terms)
        for term, frequency in counts.items():
            self._terms[term][chunk.id] = frequency

    def _refresh_average_length(self) -> None:
        self._avg_length = sum(self._lengths.values()) / len(self._lengths) if self._lengths else 0.0

    def lexical_search(
        self, query: str, allowed_ids: set[str], limit: int, *, k1: float = 1.5, b: float = 0.75
    ) -> list[LexicalHit]:
        """Return BM25-ranked candidates restricted to the caller's filtered scope."""
        query_terms = tokenize(query)
        if not query_terms or not allowed_ids or not self._chunks:
            return []
        scores: dict[str, float] = defaultdict(float)
        total_docs = len(self._chunks)
        for term in query_terms:
            posting = self._terms.get(term)
            if not posting:
                continue
            df = len(posting)
            idf = math.log(1.0 + (total_docs - df + 0.5) / (df + 0.5))
            for chunk_id, frequency in posting.items():
                if chunk_id not in allowed_ids:
                    continue
                length = self._lengths[chunk_id]
                norm = k1 * (1.0 - b + b * length / max(self._avg_length, 1.0))
                scores[chunk_id] += idf * frequency * (k1 + 1.0) / (frequency + norm)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [LexicalHit(chunk_id, score) for chunk_id, score in ranked[:limit]]

    def vector_search(
        self, query_vector: list[float], allowed_ids: set[str], limit: int
    ) -> list[tuple[str, float]]:
        """Return exact cosine-similarity results for the selected chunks."""
        query_norm = math.sqrt(sum(value * value for value in query_vector))
        if query_norm == 0:
            raise ValueError("query_vector must not be a zero vector")
        hits: list[tuple[str, float]] = []
        for chunk_id in allowed_ids:
            chunk = self._chunks.get(chunk_id)
            if chunk is None or chunk.vector is None:
                continue
            if len(chunk.vector) != len(query_vector):
                raise ValueError("query vector dimension does not match stored vector dimension")
            vector_norm = math.sqrt(sum(value * value for value in chunk.vector))
            if vector_norm == 0:
                continue
            dot = sum(a * b for a, b in zip(query_vector, chunk.vector))
            hits.append((chunk_id, dot / (query_norm * vector_norm)))
        hits.sort(key=lambda item: (-item[1], item[0]))
        return hits[:limit]
