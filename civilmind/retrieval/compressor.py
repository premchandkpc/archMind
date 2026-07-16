"""ContextCompressor — extractive sentence compression.

Keeps only the most relevant sentences from each chunk.
Reduces noise and token count for the LLM.
"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger()

MIN_SENTENCES = 2
MAX_SENTENCE_RATIO = 0.5


class ContextCompressor:
    """Compress chunks by removing irrelevant sentences."""

    def compress(self, query: str, content: str) -> str:
        """Keep only the most query-relevant sentences from content.

        Args:
            query: The search query.
            content: The chunk text to compress.

        Returns:
            Compressed text with only relevant sentences.
        """
        if not content or not content.strip():
            return content

        sentences = self._split_sentences(content)
        if len(sentences) <= MIN_SENTENCES:
            return content

        query_words = set(self._tokenize(query))
        if not query_words:
            return content

        scored = []
        for i, sent in enumerate(sentences):
            sent_words = self._tokenize(sent)
            if not sent_words:
                continue
            overlap = len(query_words & sent_words)
            position_boost = 1.0 + (0.1 / (i + 1))
            score = (overlap / len(sent_words)) * position_boost
            scored.append((sent, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        keep_count = max(MIN_SENTENCES, int(len(sentences) * MAX_SENTENCE_RATIO))

        kept = set(id(s) for s, _ in scored[:keep_count])
        result = [sent for sent in sentences if id(sent) in kept]

        return " ".join(result)

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        text = re.sub(r"\s+", " ", text).strip()
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"[a-zA-Z]+", text.lower()))
