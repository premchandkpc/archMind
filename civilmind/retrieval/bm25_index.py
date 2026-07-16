"""BM25Index — keyword search for exact term matching.

BM25 complements vector search: vectors miss exact keywords like "IS456 clause 5.3".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog
from rank_bm25 import BM25Okapi

from civilmind.config import BM25_TOP_K, MIN_CORPUS_FOR_BM25

logger = structlog.get_logger()


@dataclass
class BM25Result:
    id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class BM25Index:
    """BM25 keyword search index over document chunks."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._corpus: list[dict[str, Any]] = []
        self._tokenized: list[list[str]] = []
        self._index: BM25Okapi | None = None

    def build(self, documents: list[dict[str, Any]]) -> None:
        """Build BM25 index from document chunks.

        Each document dict must have:
            - "id": str
            - "content": str
            - "metadata": dict (optional)
        """
        self._corpus = list(documents)
        self._tokenized = [self._tokenize(d.get("content", "")) for d in documents]
        self._index = BM25Okapi(self._tokenized, k1=self._k1, b=self._b)
        logger.info("BM25 index built", doc_count=len(self._corpus))

    def search(self, query: str, top_k: int = BM25_TOP_K) -> list[BM25Result]:
        """Keyword search with BM25 scoring.

        Returns empty list if corpus is too small or no index built.
        """
        if not self._index or len(self._corpus) < MIN_CORPUS_FOR_BM25:
            if self._corpus:
                logger.debug(
                    "Corpus too small for BM25, skipping",
                    corpus_size=len(self._corpus),
                    min_size=MIN_CORPUS_FOR_BM25,
                )
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = self._index.get_scores(query_tokens)
        ranked = sorted(
            [
                BM25Result(
                    id=self._corpus[i]["id"],
                    content=self._corpus[i].get("content", ""),
                    score=float(scores[i]),
                    metadata=self._corpus[i].get("metadata", {}) or {},
                )
                for i in range(len(self._corpus))
                if scores[i] > 0
            ],
            key=lambda x: x.score,
            reverse=True,
        )

        return ranked[:top_k]

    def add_documents(self, documents: list[dict[str, Any]]) -> None:
        """Add documents and rebuild index."""
        self._corpus.extend(documents)
        self.build(self._corpus)

    def remove_documents(self, doc_ids: list[str]) -> None:
        """Remove documents by ID and rebuild index."""
        doc_ids_set = set(doc_ids)
        self._corpus = [d for d in self._corpus if d["id"] not in doc_ids_set]
        if self._corpus:
            self.build(self._corpus)
        else:
            self._corpus = []
            self._tokenized = []
            self._index = None

    @property
    def size(self) -> int:
        return len(self._corpus)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        text = text.lower()
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        return [t for t in text.split() if len(t) > 1]
