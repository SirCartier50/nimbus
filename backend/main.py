import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from agents.bodyguard import start_bodyguard, stop_bodyguard
from auth import auth_middleware
from routes.chat import router as chat_router
from routes.dashboard import router as dashboard_router
from routes.settings import router as settings_router
from routes.workspace import router as workspace_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_bodyguard()
    yield
    stop_bodyguard()


app = FastAPI(
    title="Nimbus AI",
    description="Agentic AWS Management System — Amazon Nova AI Hackathon",
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

# Clerk JWT auth — protects all /api/* routes
app.middleware("http")(auth_middleware)

app.include_router(chat_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(workspace_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "nimbus"}
