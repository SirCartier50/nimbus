import asyncio
import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

load_dotenv()

from db.engine import Base
from db import models  # noqa: F401 — populates Base.metadata

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.getenv("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


# Migrations are the container's release step (see docker-compose.yml), so a DB
# that isn't reachable *yet* would crash the backend and hand it to Docker's
# restart loop. That happens routinely: a Supabase pooler answering
# `(ENOTFOUND) tenant/user ... not found` while the project wakes, or Postgres
# still booting in a fresh compose stack. Retry the CONNECT with backoff; a
# failure inside a migration is a real bug and still aborts immediately.
_CONNECT_ATTEMPTS = 6
_CONNECT_BACKOFF = 3.0  # seconds; ~45s total before giving up


async def run_async_migrations() -> None:
    """Run migrations using an async engine (driver is asyncpg, not psycopg2)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        for attempt in range(1, _CONNECT_ATTEMPTS + 1):
            try:
                connection_cm = connectable.connect()
                connection = await connection_cm.__aenter__()
                break
            except Exception as e:
                if attempt == _CONNECT_ATTEMPTS:
                    raise
                delay = _CONNECT_BACKOFF * attempt
                print(
                    f"alembic: database not reachable ({type(e).__name__}: {e}); "
                    f"retrying in {delay:.0f}s [{attempt}/{_CONNECT_ATTEMPTS - 1}]",
                    flush=True,
                )
                await asyncio.sleep(delay)

        try:
            await connection.run_sync(do_run_migrations)
        finally:
            await connection_cm.__aexit__(None, None, None)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
