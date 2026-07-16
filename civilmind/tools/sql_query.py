"""SQLQueryTool — read-only PostgreSQL queries.

Agents query metadata without touching the ORM layer directly.
All queries are read-only, parameterized, and audited.
"""

from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from civilmind.settings import settings
from civilmind.tools.base import BaseTool, ToolResult

logger = structlog.get_logger()

QUERY_TIMEOUT_SECONDS = 5
MAX_ROWS = 1000
READ_ONLY_KEYWORDS = frozenset(
    {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT", "REVOKE"}
)


class SQLQueryTool(BaseTool):
    """Read-only SQL query tool for PostgreSQL."""

    name = "sql_query"
    description = "Query the project database (read-only)"
    category = "data"

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or settings.DATABASE_URL_SYNC

    async def execute(
        self,
        query: str,
        params: list[Any] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a parameterized read-only SQL query.

        Args:
            query: SQL SELECT statement (no INSERT/UPDATE/DELETE).
            params: Positional parameters for the query.

        Returns:
            ToolResult with list of row dicts.
        """
        normalized = query.strip().upper()

        # Reject writes
        for keyword in READ_ONLY_KEYWORDS:
            if keyword in normalized.split():
                return ToolResult(
                    success=False,
                    error=f"Rejected: '{keyword}' statements not allowed. Read-only access.",
                )

        # Must be SELECT or WITH (CTE)
        if not (normalized.startswith("SELECT") or normalized.startswith("WITH")):
            return ToolResult(
                success=False,
                error="Only SELECT or WITH (CTE) queries allowed.",
            )

        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(self._dsn, command_timeout=QUERY_TIMEOUT_SECONDS)
            rows = await conn.fetch(query, *(params or []))

            result = [dict(row) for row in rows[:MAX_ROWS]]

            logger.info(
                "SQL query executed",
                query_preview=query[:80],
                rows_returned=len(result),
                truncated=len(rows) > MAX_ROWS,
            )

            return ToolResult(
                success=True,
                data=result,
                metadata={
                    "rows_returned": len(result),
                    "truncated": len(rows) > MAX_ROWS,
                    "max_rows": MAX_ROWS,
                },
            )

        except asyncpg.QueryCanceledError:
            logger.warning("SQL query timed out", query_preview=query[:80])
            return ToolResult(
                success=False,
                error=f"Query timed out after {QUERY_TIMEOUT_SECONDS}s",
            )

        except Exception as e:
            logger.error("SQL query failed", error=str(e))
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
            )

        finally:
            if conn:
                await conn.close()
