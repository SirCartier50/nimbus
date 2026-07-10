"""Tests for the per-user token-bucket rate limiter (SEC-2). Pure logic tests on
TokenBucket/RateLimiter plus middleware wiring through a real (tiny) FastAPI app,
mirroring test_auth.py's approach — no network, no DB."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ratelimit
from ratelimit import RateLimiter, TokenBucket, rate_limit_middleware


# ---------------------------------------------------------------------------
# TokenBucket
# ---------------------------------------------------------------------------


def test_bucket_allows_up_to_capacity_then_blocks():
    b = TokenBucket(per_minute=3, now=100.0)
    assert b.try_consume(100.0) == 0.0
    assert b.try_consume(100.0) == 0.0
    assert b.try_consume(100.0) == 0.0
    wait = b.try_consume(100.0)
    assert wait > 0.0


def test_bucket_refills_over_time():
    b = TokenBucket(per_minute=60, now=0.0)  # 1 token/sec
    for _ in range(60):
        assert b.try_consume(0.0) == 0.0
    assert b.try_consume(0.0) > 0.0
    # 2 seconds later, ~2 tokens are back
    assert b.try_consume(2.0) == 0.0
    assert b.try_consume(2.0) == 0.0
    assert b.try_consume(2.0) > 0.0


def test_bucket_never_exceeds_capacity():
    b = TokenBucket(per_minute=2, now=0.0)
    # A very long idle period must not bank more than `capacity` tokens.
    assert b.try_consume(10_000.0) == 0.0
    assert b.try_consume(10_000.0) == 0.0
    assert b.try_consume(10_000.0) > 0.0


def test_retry_after_reflects_refill_rate():
    b = TokenBucket(per_minute=60, now=0.0)  # 1 token/sec
    b.tokens = 0.0
    wait = b.try_consume(0.0)
    assert wait == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# RateLimiter — per-user / per-bucket isolation
# ---------------------------------------------------------------------------


def test_users_have_independent_buckets():
    limiter = RateLimiter()
    for _ in range(5):
        assert limiter.check("user-a", "chat", per_minute=5) == 0.0
    assert limiter.check("user-a", "chat", per_minute=5) > 0.0
    # user-b is untouched by user-a's exhaustion
    assert limiter.check("user-b", "chat", per_minute=5) == 0.0


def test_buckets_are_independent_per_category():
    limiter = RateLimiter()
    for _ in range(5):
        assert limiter.check("user-a", "chat", per_minute=5) == 0.0
    assert limiter.check("user-a", "chat", per_minute=5) > 0.0
    assert limiter.check("user-a", "default", per_minute=5) == 0.0


# ---------------------------------------------------------------------------
# Middleware wiring — real FastAPI app, fake auth injecting user_id
# ---------------------------------------------------------------------------


def _make_app(user_id: str | None = "user-1") -> FastAPI:
    app = FastAPI()
    app.middleware("http")(rate_limit_middleware)

    # Outermost (registered last), like real auth in main.py: sets user_id first.
    @app.middleware("http")
    async def _fake_auth(request, call_next):
        if user_id is not None:
            request.state.user_id = user_id
        return await call_next(request)

    @app.post("/api/chat")
    def chat():
        return {"ok": True}

    @app.get("/api/sessions")
    def sessions():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    """Each test gets its own bucket table so tests can't starve each other."""
    monkeypatch.setattr(ratelimit, "_limiter", RateLimiter())


def test_chat_gets_tight_budget_and_429s(monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_PER_MINUTE", 3)
    client = TestClient(_make_app())
    for _ in range(3):
        assert client.post("/api/chat").status_code == 200
    resp = client.post("/api/chat")
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1
    assert "detail" in resp.json()


def test_non_chat_routes_use_default_budget(monkeypatch):
    monkeypatch.setattr(ratelimit, "CHAT_PER_MINUTE", 1)
    client = TestClient(_make_app())
    assert client.post("/api/chat").status_code == 200
    assert client.post("/api/chat").status_code == 429
    # default bucket unaffected by the chat bucket being exhausted
    assert client.get("/api/sessions").status_code == 200


def test_non_api_paths_are_never_limited(monkeypatch):
    monkeypatch.setattr(ratelimit, "DEFAULT_PER_MINUTE", 1)
    client = TestClient(_make_app())
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_requests_without_user_id_pass_through():
    # e.g. unit tests mounting routes without auth — the limiter must not guess a key.
    client = TestClient(_make_app(user_id=None))
    for _ in range(5):
        assert client.get("/api/sessions").status_code == 200
