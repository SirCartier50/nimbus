import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from agents.bodyguard import start_bodyguard, stop_bodyguard
from auth import auth_middleware
from db.engine import engine
from ratelimit import rate_limit_middleware
from routes.chat import router as chat_router
from routes.dashboard import router as dashboard_router
from routes.sessions import router as sessions_router
from routes.settings import router as settings_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_bodyguard()
    yield
    stop_bodyguard()
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

app.include_router(chat_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(settings_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "nimbus"}
