"""Standalone Bodyguard worker (PROD-3.5).

Runs the patrol loop as its own process instead of a daemon task inside the API:
    python worker.py

Why it's separate: the patrol is a singleton — run the API with N replicas and an
in-process daemon patrols every account N times per cycle (N× the AWS calls, N×
the "stop idle instance" races). The worker is deployed as exactly one replica;
the API replicas only ever READ bodyguard state, which lives in Postgres.

The API must not also start the daemon when this worker runs — set
BODYGUARD_IN_API=false on the API (docker-compose.yml does).
"""
import asyncio
import logging
import signal

from dotenv import load_dotenv

load_dotenv()

from config import validate_environment  # noqa: E402 — needs env loaded first
from observability import setup_logging, setup_sentry  # noqa: E402

setup_logging()
setup_sentry()
validate_environment("worker")

from agents import bodyguard  # noqa: E402
from db.engine import engine  # noqa: E402

logger = logging.getLogger("worker")


async def main() -> None:
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(bodyguard.run_forever())

    def _shutdown() -> None:
        logger.info("Shutdown signal received — stopping patrol loop")
        bodyguard.stop_bodyguard()
        task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            # Windows dev runs — Ctrl+C raises KeyboardInterrupt instead; fine.
            pass

    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        await engine.dispose()
    logger.info("Worker exited cleanly")


if __name__ == "__main__":
    asyncio.run(main())
