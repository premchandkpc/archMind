"""Pipeline workers — background event consumers with retry logic."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from civilmind.events.bus import EventBus, EventConsumer
from civilmind.events.handlers import (
    PermanentError,
    RetryableError,
    handle_document_chunked,
    handle_document_embedded,
    handle_document_parsed,
    handle_document_uploaded,
)
from civilmind.pipeline.chunker import Chunker
from civilmind.pipeline.embedder import EmbedderFactory
from civilmind.pipeline.parser import DocumentParser
from civilmind.settings import settings
from civilmind.vector.qdrant_store import QdrantStore

logger = structlog.get_logger()

RETRY_DELAYS = [0, 5, 25]


async def _run_handler(
    handler: Callable[..., Awaitable[None]],
    event: dict[str, Any],
    **deps: object,
) -> None:
    last_error: Exception | None = None
    for attempt, delay in enumerate(RETRY_DELAYS):
        if attempt > 0:
            logger.info(
                "Retrying handler", event_type=event.get("event_type"), attempt=attempt, delay=delay
            )
            await asyncio.sleep(delay)
        try:
            await handler(event, **deps)
            return
        except PermanentError as e:
            logger.error("Permanent failure, moving to dead-letter", error=str(e), event=event)
            raise
        except RetryableError as e:
            last_error = e
            logger.warning("Retryable error", error=str(e), event=event, attempt=attempt)
        except Exception as e:
            last_error = e
            logger.warning("Unexpected retryable error", error=str(e), event=event, attempt=attempt)

    raise RetryableError(f"All retries exhausted: {last_error}") from last_error


class PipelineWorker:
    """Background worker consuming pipeline events from Redis Streams."""

    def __init__(
        self,
        event_bus: EventBus,
        consumer_name: str,
        group: str = "pipeline-workers",
        stream: str = "ingestion",
    ) -> None:
        self._bus = event_bus
        self._consumer = EventConsumer(event_bus._redis)
        self._consumer_name = consumer_name
        self._group = group
        self._stream = stream
        self._running = False

        self._parser = DocumentParser()
        self._chunker = Chunker()
        self._embedder = EmbedderFactory.create()
        self._store = QdrantStore(
            url=settings.QDRANT_URL,
            api_key=None,
        )

    async def run(self) -> None:
        self._running = True
        logger.info(
            "Worker started",
            consumer=self._consumer_name,
            group=self._group,
            stream=self._stream,
        )

        while self._running:
            event = await self._consumer.consume(
                self._stream,
                self._group,
                self._consumer_name,
                block=2000,
            )

            if event is None:
                continue

            event_type = event.get("event_type", "")
            event_id = event.get("_event_id", "")

            handler = self._get_handler(event_type)
            if handler is None:
                logger.warning(
                    "Unknown event type, acking", event_type=event_type, event_id=event_id
                )
                await self._consumer.ack(self._stream, self._group, event_id)
                continue

            try:
                await _run_handler(
                    handler,
                    event,
                    parser=self._parser,
                    chunker=self._chunker,
                    embedder=self._embedder,
                    store=self._store,
                    bus=self._bus,
                )
                await self._consumer.ack(self._stream, self._group, event_id)
                logger.info("Handler succeeded", event_type=event_type, event_id=event_id)
            except PermanentError as e:
                logger.error(
                    "Handler permanently failed",
                    event_type=event_type,
                    event_id=event_id,
                    error=str(e),
                )
                await self._consumer.ack(self._stream, self._group, event_id)
            except RetryableError as e:
                logger.error(
                    "Handler exhausted retries",
                    event_type=event_type,
                    event_id=event_id,
                    error=str(e),
                )
                await self._consumer.ack(self._stream, self._group, event_id)

    def stop(self) -> None:
        self._running = False
        logger.info("Worker stopping", consumer=self._consumer_name)

    def _get_handler(
        self,
        event_type: str,
    ) -> Callable[..., Awaitable[None]] | None:
        mapping: dict[str, Callable[..., Awaitable[None]]] = {
            "document.uploaded": handle_document_uploaded,
            "document.parsed": handle_document_parsed,
            "document.chunked": handle_document_chunked,
            "document.embedded": handle_document_embedded,
        }
        return mapping.get(event_type)
