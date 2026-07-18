import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

load_dotenv()

from config import validate_environment
from observability import metrics_endpoint, observability_middleware, setup_logging, setup_sentry

setup_logging()
setup_sentry()
validate_environment("api")

from agents.bodyguard import start_bodyguard, stop_bodyguard
from auth import auth_middleware
from db.engine import engine
from ratelimit import rate_limit_middleware
from routes import chat as chat_module
from routes.chat import router as chat_router
from routes.dashboard import router as dashboard_router
from routes.sessions import router as sessions_router
from routes.settings import router as settings_router

logger = logging.getLogger("main")

# How long shutdown waits for in-flight chat turns before giving up. Must be
# shorter than the container's stop grace period (docker-compose
# stop_grace_period / K8s terminationGracePeriodSeconds) or the drain gets
# SIGKILLed mid-wait and buys nothing.
SHUTDOWN_DRAIN_SECONDS = float(os.getenv("SHUTDOWN_DRAIN_SECONDS", "55"))


# Whether this API process hosts the Bodyguard patrol loop. Default true so a
# bare `uvicorn main:app` dev run still patrols; production compose sets it
# false and runs worker.py as a dedicated single-replica process instead —
# N API replicas with in-process daemons would patrol every account N times.
BODYGUARD_IN_API = os.getenv("BODYGUARD_IN_API", "true").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if BODYGUARD_IN_API:
        start_bodyguard()
    yield
    if BODYGUARD_IN_API:
        stop_bodyguard()
    # A restart/deploy must not kill a mid-deploy turn: real AWS resources may be
    # provisioning, and without the Deployment row/history write the user has no
    # record of what happened. Client disconnects were already protected (the turn
    # runs in a background task); this extends the same guarantee to server exit.
    pending = set(chat_module._turn_tasks)
    if pending:
        logger.warning("Shutdown: draining %d in-flight chat turn(s)…", len(pending))
        done, still_pending = await asyncio.wait(pending, timeout=SHUTDOWN_DRAIN_SECONDS)
        if still_pending:
            logger.error("Shutdown: %d turn(s) did not finish within drain window", len(still_pending))
    await engine.dispose()


app = FastAPI(
    title="Nimbus AI",
    description="Agentic AWS Management System",
    version="1.0.0",
    lifespan=lifespan,
)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware runs outermost-last-registered: auth (below) verifies the token first,
# then the rate limiter (registered here, so inner) buckets by the verified user_id.
app.middleware("http")(rate_limit_middleware)

# Clerk JWT auth — protects all /api/* routes
app.middleware("http")(auth_middleware)

# Registered last = outermost: request ids + metrics must see every request,
# including the ones auth or the rate limiter reject.
app.middleware("http")(observability_middleware)

app.include_router(chat_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(settings_router, prefix="/api")


@app.get("/metrics")
async def metrics():
    """Prometheus exposition. Unauthenticated by design (no user data in it,
    just counters/histograms); the reverse proxy decides whether to expose it."""
    return metrics_endpoint()


@app.get("/health")
async def health():
    """Liveness: is the process up. Deliberately does NOT touch dependencies —
    restarting the app because the database blipped only makes an outage worse."""
    return {"status": "ok", "service": "nimbus"}


@app.get("/health/ready")
async def ready():
    """Readiness: should traffic be routed here. Fails when the DB is unreachable
    so a load balancer / orchestrator can pull the instance out of rotation."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable", "reason": "database unreachable"})
    return {"status": "ready", "service": "nimbus"}
