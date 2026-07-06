"""Shared pytest fixtures.

Env vars are force-set (not setdefault) before any app module is imported,
so a test run can never accidentally pick up a developer's real .env or
shell-exported production secrets (e.g. a real Supabase DATABASE_URL).
Override DATABASE_URL via TEST_DATABASE_URL if your local Postgres isn't at
the default below.
"""
import asyncio
import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://nimbus:nimbus@localhost:5432/nimbus_test"
)
os.environ["AWS_ACCESS_KEY_ID"] = "test-access-key-id"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test-secret-access-key"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["CLERK_ISSUER"] = "https://example.clerk.test"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import db.models  # noqa: F401 — populates Base.metadata before any create_all call
from db.crud import clear_user_cache
from db.engine import Base, engine, async_session_local
from db.deps import get_db

TEST_USER_SUB = "test-clerk-user-id"


async def _try_connect(database_url: str):
    # asyncpg.connect() doesn't understand SQLAlchemy's "+asyncpg" dialect suffix
    raw_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(raw_url)
    await conn.close()


def _db_reachable() -> bool:
    """One-time probe so integration tests skip cleanly with a clear reason
    instead of hanging/erroring confusingly when no test Postgres is running."""
    try:
        asyncio.run(asyncio.wait_for(_try_connect(os.environ["DATABASE_URL"]), timeout=2))
        return True
    except Exception:
        return False


DB_AVAILABLE = _db_reachable()

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE, reason="No reachable test Postgres — set TEST_DATABASE_URL or run one locally"
)


@pytest_asyncio.fixture
async def db_session():
    """Fresh schema per test: create_all before, drop_all after. Simpler and
    safer to reason about than a shared transaction/rollback across asyncpg.

    Also clears crud.py's process-wide user-id cache — without this, a clerk_user_id
    cached against one test's schema would resolve to a UUID that doesn't exist in
    the next test's freshly-recreated (empty) users table, causing FK violations."""
    clear_user_cache()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_local() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    clear_user_cache()


@pytest_asyncio.fixture
async def client(db_session, monkeypatch):
    """Authenticated httpx AsyncClient against the real FastAPI app. Auth
    middleware and the DB are real code paths — only Clerk's network JWKS
    lookup is mocked, and the app's get_db dependency is pointed at this
    test's db_session so route code and test assertions see the same data."""
    import auth

    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": TEST_USER_SUB})

    import main

    async def _override_get_db():
        yield db_session

    main.app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=main.app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers={"Authorization": "Bearer faketoken"}
    ) as c:
        yield c

    main.app.dependency_overrides.clear()
