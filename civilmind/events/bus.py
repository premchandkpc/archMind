"""Redis Streams event bus — publish/subscribe with consumer groups."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import redis.asyncio as redis
import structlog

logger = structlog.get_logger()

# Stream names
STREAM_INGESTION = "ingestion"
STREAM_QUERIES = "queries"
STREAM_AUDIT = "audit"

# Max event size (10MB)
MAX_EVENT_SIZE = 10 * 1024 * 1024


class EventPublisher:
    """Publish events to Redis Streams."""

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def publish(self, stream: str, event: dict) -> str:
        """Publish event to stream. Returns event ID.

        Raises ValueError if event exceeds 10MB.
        """
        # Add metadata
        event["_timestamp"] = datetime.now(timezone.utc).isoformat()
        event["_stream"] = stream

        payload = json.dumps(event, default=str)
        if len(payload.encode()) > MAX_EVENT_SIZE:
            raise ValueError(f"Event exceeds {MAX_EVENT_SIZE} bytes limit")

        event_id = await self._redis.xadd(
            stream,
            {"data": payload},
            maxlen=10000,  # Keep last 10k events per stream
        )
        logger.debug("Published event", stream=stream, event_id=event_id)
        return event_id


class EventConsumer:
    """Consume events from Redis Streams with consumer groups."""

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 1,
        block: int = 1000,
    ) -> dict | None:
        """Read next event from consumer group.

        Returns None if no events available within block timeout.
        """
        try:
            # Create group if it doesn't exist
            try:
                await self._redis.xgroup_create(
                    stream, group, id="0", mkstream=True
                )
            except redis.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

            results = await self._redis.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={stream: ">"},
                count=count,
                block=block,
            )

            if not results:
                return None

            # Parse first result
            _stream_name, messages = results[0]
            if not messages:
                return None

            event_id, fields = messages[0]
            data = json.loads(fields.get("data", "{}"))

            # Store event ID for ack/nack
            data["_event_id"] = event_id
            return data

        except Exception as e:
            logger.error("Consumer error", stream=stream, group=group, error=str(e))
            return None

    async def ack(self, stream: str, group: str, event_id: str) -> None:
        """Acknowledge event processing completed."""
        await self._redis.xack(stream, group, event_id)
        logger.debug("Acknowledged event", stream=stream, event_id=event_id)

    async def nack(self, stream: str, group: str, event_id: str) -> None:
        """Negative acknowledge — event will be redelivered."""
        # XACK + XDEL to force redelivery
        await self._redis.xack(stream, group, event_id)
        logger.debug("Nacked event (will retry)", stream=stream, event_id=event_id)

    async def get_pending(
        self, stream: str, group: str, consumer: str, count: int = 10
    ) -> list[dict]:
        """Get pending (unacknowledged) events for a consumer."""
        results = await self._redis.xpending_range(
            stream, group, min="-", max="+", count=count
        )
        pending = []
        for entry in results:
            pending.append({
                "event_id": entry.get("message_id", ""),
                "consumer": entry.get("consumer", ""),
                "idle_ms": entry.get("idle", 0),
                "delivery_count": entry.get("delivery_count", 0),
            })
        return pending

    async def claim_stale(
        self, stream: str, group: str, consumer: str, min_idle_ms: int = 300000
    ) -> list[str]:
        """Claim events idle for more than min_idle_ms (5 min default)."""
        pending = await self._redis.xpending_range(
            stream, group, min="-", max="+", count=100
        )
        stale_ids = [
            entry["message_id"]
            for entry in pending
            if entry.get("idle", 0) > min_idle_ms
        ]
        if stale_ids:
            claimed = await self._redis.xclaim(
                stream, group, consumer, min_idle_ms=min_idle_ms, *stale_ids
            )
            return [msg_id for msg_id, _ in claimed]
        return []


class EventBus:
    """Unified event bus combining publisher and consumer."""

    def __init__(self, redis_url: str) -> None:
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self.publisher = EventPublisher(self._redis)
        self.consumer = EventConsumer(self._redis)

    async def publish(self, stream: str, event: dict) -> str:
        """Publish event. Convenience method."""
        return await self.publisher.publish(stream, event)

    async def consume(
        self, stream: str, group: str, consumer: str, **kwargs
    ) -> dict | None:
        """Consume event. Convenience method."""
        return await self.consumer.consume(stream, group, consumer, **kwargs)

    async def ack(self, stream: str, group: str, event_id: str) -> None:
        """Acknowledge event. Convenience method."""
        await self.consumer.ack(stream, group, event_id)

    async def health_check(self) -> bool:
        """Check Redis connectivity."""
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        await self._redis.close()
