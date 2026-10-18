"""Standalone HTTP API for CivilMind Native DB."""

from __future__ import annotations

import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from civilmind.native_db.models import Chunk
from civilmind.native_db.store import NativeStore

logger = structlog.get_logger()


class ChunkWrite(BaseModel):
    """Payload to insert or replace one searchable chunk."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=256)
    project_id: str = Field(min_length=1, max_length=256)
    document_id: str = Field(min_length=1, max_length=256)
    revision_id: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=2_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    vector: list[float] | None = None


class SearchRequest(BaseModel):
    """Hybrid retrieval query."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=20_000)
    project_id: str = Field(min_length=1, max_length=256)
    metadata_filter: dict[str, Any] = Field(default_factory=dict)
    query_vector: list[float] | None = None
    limit: int = Field(default=10, ge=1, le=100)


def create_app(
    data_dir: str | Path | None = None,
    api_token: str | None = None,
    store: NativeStore | None = None,
) -> FastAPI:
    """Create the standalone database service."""
    owns_store = store is None
    native_store = store or NativeStore(
        data_dir or os.getenv("CIVILMIND_DB_DATA_DIR", ".civilmind-native-db")
    )
    expected_token = api_token if api_token is not None else os.getenv("CIVILMIND_DB_TOKEN", "")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.native_store = native_store
        yield
        if owns_store:
            native_store.close()

    app = FastAPI(
        title="CivilMind Native DB",
        version="0.1.0",
        description="Standalone durable hybrid retrieval engine for CivilMind chunks.",
        lifespan=lifespan,
    )

    async def authorize(authorization: str | None = Header(default=None)) -> None:
        if not expected_token:
            return
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, expected_token):
            raise HTTPException(status_code=401, detail="invalid bearer token")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", **native_store.stats()}

    @app.put("/v1/chunks", dependencies=[Depends(authorize)])
    async def put_chunk(payload: ChunkWrite) -> dict[str, Any]:
        try:
            seq = await asyncio.to_thread(
                native_store.upsert,
                Chunk(
                    id=payload.id, project_id=payload.project_id, document_id=payload.document_id,
                    revision_id=payload.revision_id, content=payload.content,
                    metadata=payload.metadata, vector=payload.vector,
                ),
            )
            return {"id": payload.id, "sequence": seq, "status": "committed"}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("native DB upsert failed", error=str(exc))
            raise HTTPException(status_code=500, detail="storage operation failed") from exc

    @app.delete("/v1/chunks/{chunk_id}", dependencies=[Depends(authorize)])
    async def delete_chunk(chunk_id: str) -> dict[str, Any]:
        try:
            seq = await asyncio.to_thread(native_store.delete, chunk_id)
            return {"id": chunk_id, "sequence": seq, "status": "deleted"}
        except Exception as exc:
            logger.error("native DB delete failed", error=str(exc))
            raise HTTPException(status_code=500, detail="storage operation failed") from exc

    @app.post("/v1/search", dependencies=[Depends(authorize)])
    async def search(payload: SearchRequest) -> dict[str, Any]:
        try:
            hits = await asyncio.to_thread(
                native_store.search, payload.query, project_id=payload.project_id,
                metadata_filter=payload.metadata_filter, query_vector=payload.query_vector,
                limit=payload.limit,
            )
            return {
                "results": [
                    {
                        "id": hit.chunk.id, "project_id": hit.chunk.project_id,
                        "document_id": hit.chunk.document_id, "revision_id": hit.chunk.revision_id,
                        "content": hit.chunk.content, "metadata": hit.chunk.metadata,
                        "score": hit.score, "lexical_score": hit.lexical_score,
                        "vector_score": hit.vector_score, "lexical_rank": hit.lexical_rank,
                        "vector_rank": hit.vector_rank,
                    }
                    for hit in hits
                ],
                "count": len(hits), "sequence": native_store.sequence,
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("native DB search failed", error=str(exc))
            raise HTTPException(status_code=500, detail="search operation failed") from exc

    @app.get("/v1/stats", dependencies=[Depends(authorize)])
    async def stats() -> dict[str, Any]:
        return native_store.stats()

    return app


app = create_app()
