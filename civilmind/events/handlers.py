"""Pipeline event handlers — one handler per pipeline stage."""

from __future__ import annotations

from typing import Any

import structlog

from civilmind.config import DEFAULT_COLLECTION
from civilmind.events.bus import STREAM_INGESTION, EventBus
from civilmind.pipeline.chunker import Chunker
from civilmind.pipeline.embedder import BaseEmbedder
from civilmind.pipeline.parser import DocumentParser
from civilmind.vector.qdrant_store import QdrantStore

logger = structlog.get_logger()


class RetryableError(Exception):
    """Transient error — retry with backoff."""


class PermanentError(Exception):
    """Fatal error — send to dead-letter queue."""


async def handle_document_uploaded(
    event: dict[str, Any],
    parser: DocumentParser,
    chunker: Chunker,
    bus: EventBus,
) -> None:
    """Parse document → publish document.parsed."""
    file_path = event.get("file_path", "")
    document_id = event.get("document_id", "")
    project_id = event.get("project_id", "")

    if not file_path or not document_id:
        raise PermanentError("Missing file_path or document_id in event")

    logger.info("Parsing document", document_id=document_id, file_path=file_path)
    elements = await parser.parse(file_path)
    logger.info("Parsed elements", document_id=document_id, count=len(elements))

    await bus.publish(
        STREAM_INGESTION,
        {
            "event_type": "document.parsed",
            "document_id": document_id,
            "project_id": project_id,
            "file_path": file_path,
            "elements": [
                {
                    "type": e.type.value,
                    "content": e.content,
                    "page_number": e.page_number,
                    "table_data": e.table_data,
                    "image_path": e.image_path,
                }
                for e in elements
            ],
        },
    )


async def handle_document_parsed(event: dict[str, Any], chunker: Chunker, bus: EventBus) -> None:
    """Chunk parsed elements → publish document.chunked."""
    from civilmind.pipeline.parser import ElementType, ParsedElement

    document_id = event.get("document_id", "")
    project_id = event.get("project_id", "")

    raw_elements = event.get("elements", [])
    elements = [
        ParsedElement(
            type=ElementType(el["type"]),
            content=el.get("content", ""),
            page_number=el.get("page_number"),
            table_data=el.get("table_data"),
            image_path=el.get("image_path"),
        )
        for el in raw_elements
    ]

    chunks = await chunker.chunk(elements, document_id=document_id, project_id=project_id)
    logger.info("Chunked document", document_id=document_id, chunk_count=len(chunks))

    await bus.publish(
        STREAM_INGESTION,
        {
            "event_type": "document.chunked",
            "document_id": document_id,
            "project_id": project_id,
            "chunks": [
                {
                    "id": c.id,
                    "content": c.content,
                    "metadata": c.metadata,
                }
                for c in chunks
            ],
        },
    )


async def handle_document_chunked(
    event: dict[str, Any],
    embedder: BaseEmbedder,
    store: QdrantStore,
    bus: EventBus,
) -> None:
    """Embed chunks → upsert to Qdrant → publish document.embedded."""
    document_id = event.get("document_id", "")
    project_id = event.get("project_id", "")
    raw_chunks = event.get("chunks", [])

    if not raw_chunks:
        logger.warning("No chunks to embed", document_id=document_id)
        await bus.publish(
            STREAM_INGESTION,
            {
                "event_type": "document.embedded",
                "document_id": document_id,
                "project_id": project_id,
                "chunks": [],
            },
        )
        return

    contents = [c["content"] for c in raw_chunks]
    vectors = await embedder.embed_batch(contents)
    logger.info("Embedded chunks", document_id=document_id, count=len(vectors))

    payloads = [c["metadata"] for c in raw_chunks]
    point_ids = await store.upsert(
        collection=DEFAULT_COLLECTION,
        vectors=vectors,
        payloads=payloads,
    )

    chunks_with_ids = []
    for raw, point_id in zip(raw_chunks, point_ids):
        chunks_with_ids.append({**raw, "embedding_id": point_id})

    await bus.publish(
        STREAM_INGESTION,
        {
            "event_type": "document.embedded",
            "document_id": document_id,
            "project_id": project_id,
            "chunks": chunks_with_ids,
        },
    )


async def handle_document_embedded(event: dict[str, Any], bus: EventBus) -> None:
    """Final step — publish document.indexed."""
    document_id = event.get("document_id", "")
    project_id = event.get("project_id", "")
    chunk_count = len(event.get("chunks", []))

    logger.info("Document indexed", document_id=document_id, chunk_count=chunk_count)

    await bus.publish(
        STREAM_INGESTION,
        {
            "event_type": "document.indexed",
            "document_id": document_id,
            "project_id": project_id,
            "chunk_count": chunk_count,
        },
    )


HANDLER_MAP: dict[str, str] = {
    "document.uploaded": "parse_document",
    "document.parsed": "chunk_document",
    "document.chunked": "embed_document",
    "document.embedded": "index_document",
}
