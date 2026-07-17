"""PostgresSaver — persist LangGraph workflow state to PostgreSQL.

Stores workflow checkpoints in the existing PostgreSQL database.
Enables state resumption, audit trails, and multi-run debugging.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger()


class PostgresSaver:
    """Checkpoint saver backed by PostgreSQL.

    Compatible with LangGraph's checkpointer interface.
    Stores each node's state as a JSONB checkpoint.

    Usage:
        checkpointer = PostgresSaver(dsn=settings.DATABASE_URL_SYNC)
        await checkpointer.setup()
        graph = build_graph(checkpointer=checkpointer)
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def setup(self) -> None:
        """Create checkpoints table if it doesn't exist."""
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                    thread_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    parent_checkpoint_id TEXT,
                    checkpoint JSONB NOT NULL,
                    metadata JSONB DEFAULT '{}',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (thread_id, checkpoint_id)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_checkpoints_thread
                ON workflow_checkpoints (thread_id, created_at DESC)
            """)
            logger.info("PostgresSaver tables created")
        finally:
            await conn.close()

    async def save(
        self,
        thread_id: str,
        checkpoint_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        parent_checkpoint_id: str | None = None,
    ) -> None:
        """Save a workflow checkpoint.

        Args:
            thread_id: Workflow thread identifier.
            checkpoint_id: Unique checkpoint ID.
            state: Serialized workflow state.
            metadata: Optional metadata (node name, latency, etc.).
            parent_checkpoint_id: Previous checkpoint for chain.
        """
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            await conn.execute(
                """
                INSERT INTO workflow_checkpoints
                    (thread_id, checkpoint_id, parent_checkpoint_id, checkpoint, metadata)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (thread_id, checkpoint_id) DO UPDATE
                SET checkpoint = EXCLUDED.checkpoint,
                    metadata = EXCLUDED.metadata
                """,
                thread_id,
                checkpoint_id,
                parent_checkpoint_id,
                json.dumps(state, default=str),
                json.dumps(metadata or {}, default=str),
            )
            logger.debug(
                "Checkpoint saved",
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
            )
        finally:
            await conn.close()

    async def load(
        self,
        thread_id: str,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Load a checkpoint. If checkpoint_id is None, load the latest.

        Args:
            thread_id: Workflow thread identifier.
            checkpoint_id: Specific checkpoint to load, or None for latest.

        Returns:
            Serialized state dict, or None if not found.
        """
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            if checkpoint_id:
                row = await conn.fetchrow(
                    """
                    SELECT checkpoint FROM workflow_checkpoints
                    WHERE thread_id = $1 AND checkpoint_id = $2
                    """,
                    thread_id,
                    checkpoint_id,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT checkpoint FROM workflow_checkpoints
                    WHERE thread_id = $1
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    thread_id,
                )

            if row is None:
                return None

            return json.loads(row["checkpoint"])
        finally:
            await conn.close()

    async def list_checkpoints(
        self,
        thread_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List checkpoints for a thread, newest first.

        Args:
            thread_id: Workflow thread identifier.
            limit: Maximum results.

        Returns:
            List of checkpoint summaries (without full state).
        """
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            rows = await conn.fetch(
                """
                SELECT checkpoint_id, parent_checkpoint_id, metadata, created_at
                FROM workflow_checkpoints
                WHERE thread_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                thread_id,
                limit,
            )
            return [
                {
                    "checkpoint_id": row["checkpoint_id"],
                    "parent_checkpoint_id": row["parent_checkpoint_id"],
                    "metadata": json.loads(row["metadata"]),
                    "created_at": row["created_at"].isoformat(),
                }
                for row in rows
            ]
        finally:
            await conn.close()

    async def delete_thread(self, thread_id: str) -> int:
        """Delete all checkpoints for a thread.

        Args:
            thread_id: Workflow thread identifier.

        Returns:
            Number of checkpoints deleted.
        """
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            result = await conn.execute(
                "DELETE FROM workflow_checkpoints WHERE thread_id = $1",
                thread_id,
            )
            count = int(result.split()[-1])
            logger.info("Deleted thread checkpoints", thread_id=thread_id, count=count)
            return count
        finally:
            await conn.close()
