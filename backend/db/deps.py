from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from db.engine import async_session_local


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_local() as session:
        yield session
