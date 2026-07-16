"""FastAPI dependency — yields async DB sessions with auto-commit/rollback."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from civilmind.db.engine import async_session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
