"""Chunker — splits parsed elements into embeddable chunks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from civilmind.config import CHUNK_OVERLAP, CHUNK_SIZE
from civilmind.pipeline.metadata import TextMetadata, extract_metadata
from civilmind.pipeline.parser import ElementType, ParsedElement

logger = structlog.get_logger()


@dataclass
class Chunk:
    id: str
    content: str
    metadata: dict[str, object] = field(default_factory=dict)
    embedding_id: str | None = None


class Chunker:
    """Split ParsedElements into Chunks for embedding."""

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
        use_semantic: bool = False,
    ) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._use_semantic = use_semantic
        self._semantic_chunker: Any = None

    def _get_semantic_chunker(self) -> Any:
        if not self._use_semantic:
            return None
        if self._semantic_chunker is None:
            try:
                from langchain_experimental.text_splitter import SemanticChunker
                from sentence_transformers import SentenceTransformer

                embedder = SentenceTransformer("BAAI/bge-base-en-v1.5")
                self._semantic_chunker = SemanticChunker(
                    embeddings=embedder,
                    breakpoint_threshold_type="percentile",
                )
            except ImportError:
                logger.warning("SemanticChunker unavailable, falling back to fixed-size")
                self._use_semantic = False
        return self._semantic_chunker

    async def chunk(
        self,
        elements: list[ParsedElement],
        document_id: str = "",
        project_id: str = "",
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        current_section: str = ""

        text_buffer: list[str] = []
        buffer_meta: dict[str, object] = {}

        def flush_buffer() -> None:
            nonlocal text_buffer
            if not text_buffer:
                return
            text = " ".join(text_buffer)
            merged_meta = dict(buffer_meta)
            merged_meta.pop("element_index", None)

            if self._use_semantic:
                sub_chunks = self._semantic_split(text, merged_meta)
                chunks.extend(sub_chunks)
            else:
                sub_chunks = self._fixed_split(text, merged_meta)
                chunks.extend(sub_chunks)

            text_buffer = []
            buffer_meta.clear()

        for el in elements:
            if el.type == ElementType.PAGE_BREAK:
                continue

            if el.type == ElementType.TITLE:
                flush_buffer()
                current_section = el.content.strip()
                continue

            if el.type == ElementType.TABLE:
                flush_buffer()
                chunk = self._chunk_from_table(el, document_id, project_id, current_section)
                if chunk:
                    chunks.append(chunk)
                continue

            if el.type == ElementType.IMAGE:
                flush_buffer()
                chunk = self._chunk_from_image(el, document_id, project_id, current_section)
                if chunk:
                    chunks.append(chunk)
                continue

            text_buffer.append(el.content)
            if not buffer_meta:
                buffer_meta = {
                    "page_number": el.page_number,
                    "element_index": el.metadata.get("element_index"),
                }

            acc_len = sum(len(t) for t in text_buffer)
            if acc_len >= self._chunk_size:
                flush_buffer()

        flush_buffer()

        for c in chunks:
            c.metadata.update(
                {
                    "document_id": document_id,
                    "project_id": project_id,
                    "section": current_section,
                    "chunk_type": c.metadata.get("chunk_type", "text"),
                }
            )

        return chunks

    def _semantic_split(self, text: str, base_meta: dict[str, object]) -> list[Chunk]:
        chunker = self._get_semantic_chunker()
        if chunker is None:
            return self._fixed_split(text, base_meta)

        try:
            docs = chunker.split_text(text)
            return [
                Chunk(
                    id=str(uuid.uuid4()),
                    content=doc if isinstance(doc, str) else doc.page_content,
                    metadata={**base_meta, "chunk_type": "text", **_extract_chunk_meta(doc)},
                )
                for doc in docs
                if (doc if isinstance(doc, str) else doc.page_content)
            ]
        except Exception as e:
            logger.warning("Semantic split failed, falling back to fixed", error=str(e))
            return self._fixed_split(text, base_meta)

    def _fixed_split(self, text: str, base_meta: dict[str, object]) -> list[Chunk]:
        words = text.split()
        if not words:
            return []

        chunks: list[Chunk] = []
        start = 0
        while start < len(words):
            end = start + self._chunk_size
            chunk_words = words[start:end]
            chunk_text = " ".join(chunk_words)
            if not chunk_text.strip():
                break

            chunks.append(
                Chunk(
                    id=str(uuid.uuid4()),
                    content=chunk_text,
                    metadata={**base_meta, "chunk_type": "text"},
                )
            )
            start += self._chunk_size - self._chunk_overlap

        return chunks

    def _chunk_from_table(
        self,
        el: ParsedElement,
        document_id: str,
        project_id: str,
        section: str,
    ) -> Chunk | None:
        if not el.table_data:
            return None

        md_lines = ["| " + " | ".join(el.table_data[0]) + " |"]
        md_lines.append("| " + " | ".join(["---"] * len(el.table_data[0])) + " |")
        for row in el.table_data[1:]:
            md_lines.append("| " + " | ".join(row) + " |")

        md = "\n".join(md_lines)
        meta = _extract_chunk_meta(el.content + " " + md)

        return Chunk(
            id=str(uuid.uuid4()),
            content=md,
            metadata={
                "document_id": document_id,
                "project_id": project_id,
                "section": section,
                "chunk_type": "table",
                "page_number": el.page_number,
                **meta,
            },
        )

    def _chunk_from_image(
        self,
        el: ParsedElement,
        document_id: str,
        project_id: str,
        section: str,
    ) -> Chunk | None:
        meta = _extract_chunk_meta(el.content)
        return Chunk(
            id=str(uuid.uuid4()),
            content=el.content,
            metadata={
                "document_id": document_id,
                "project_id": project_id,
                "section": section,
                "chunk_type": "image",
                "image_path": el.image_path or "",
                "page_number": el.page_number,
                **meta,
            },
        )


def _extract_chunk_meta(text: str) -> dict[str, object]:
    tm: TextMetadata = extract_metadata(text)
    return {
        "char_count": tm.char_count,
        "word_count": tm.word_count,
        "has_measurements": tm.has_measurements,
        "measurements": list(tm.measurements),
        "has_code_references": tm.has_code_references,
        "code_references": list(tm.code_references),
        "is_technical": tm.is_technical,
    }
