"""Health check endpoint."""

from datetime import datetime

import httpx
from fastapi import APIRouter

from civilmind.settings import settings

router = APIRouter(tags=["health"])


async def check_postgres() -> bool:
    try:
        import asyncpg

        conn = await asyncpg.connect(settings.DATABASE_URL)
        await conn.execute("SELECT 1")
        await conn.close()
        return True
    except Exception:
        return False


async def check_qdrant() -> bool:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{settings.QDRANT_URL}/healthz")
            return resp.status_code == 200
    except Exception:
        return False


async def check_minio() -> bool:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://{settings.MINIO_ENDPOINT}/minio/health/live")
            return resp.status_code == 200
    except Exception:
        return False


async def check_neo4j() -> bool:
    try:
        from neo4j import AsyncGraphDatabase

        driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
        await driver.verify_connectivity()
        await driver.close()
        return True
    except Exception:
        return False


@router.get("/health")
async def health_check():
    services = {
        "postgres": await check_postgres(),
        "qdrant": await check_qdrant(),
        "minio": await check_minio(),
        "neo4j": await check_neo4j(),
    }
    all_healthy = all(services.values())
    return {
        "status": "ok" if all_healthy else "degraded",
        "version": "0.1.0",
        "timestamp": datetime.utcnow().isoformat(),
        "services": services,
    }
