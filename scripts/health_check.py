"""Health check — verify all service connectivity."""

import asyncio
import sys


async def check_postgres() -> bool:
    try:
        import asyncpg

        c = await asyncpg.connect(
            "postgresql://civilmind:civilmind@localhost:5432/civilmind"
        )
        await c.execute("SELECT 1")
        await c.close()
        return True
    except Exception:
        return False


async def check_qdrant() -> bool:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5) as h:
            r = await h.get("http://localhost:6333/healthz")
            return r.status_code == 200
    except Exception:
        return False


async def check_minio() -> bool:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5) as h:
            r = await h.get("http://localhost:9000/minio/health/live")
            return r.status_code == 200
    except Exception:
        return False


async def check_neo4j() -> bool:
    try:
        from neo4j import AsyncGraphDatabase

        d = AsyncGraphDatabase.driver(
            "bolt://localhost:7687", auth=("neo4j", "password")
        )
        await d.verify_connectivity()
        await d.close()
        return True
    except Exception:
        return False


async def check_redis() -> bool:
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url("redis://localhost:6379/0")
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


async def main() -> None:
    checks = {
        "postgres": check_postgres,
        "qdrant": check_qdrant,
        "minio": check_minio,
        "neo4j": check_neo4j,
        "redis": check_redis,
    }

    results = {}
    for name, check in checks.items():
        results[name] = await check()

    for name, ok in results.items():
        status = "[OK]" if ok else "[--]"
        print(f"  {status} {name}")

    all_healthy = all(results.values())
    print(f"\n  All healthy: {all_healthy}")
    sys.exit(0 if all_healthy else 1)


if __name__ == "__main__":
    asyncio.run(main())
