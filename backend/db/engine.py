import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    # Fail fast with a clear message — without this, the first query dies with a
    # cryptic asyncpg TypeError long after startup looked healthy.
    raise RuntimeError("DATABASE_URL env var is not set — the backend cannot start without a database.")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    # Supabase sits behind a pooler that drops idle connections; validate each
    # one before use instead of handing a dead socket to a request.
    pool_pre_ping=True,
    # Recycle well before upstream idle timeouts so we close first.
    pool_recycle=1800,
    pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
    pool_timeout=30,
)
async_session_local = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass
