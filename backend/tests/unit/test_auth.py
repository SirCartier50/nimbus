"""Tests for the Clerk Billing claim helpers and gating dependencies. Pure functions
over a dict — no network, no real Clerk token needed (verify_clerk_token itself,
which does hit Clerk's JWKS endpoint, is exercised only via the mocked fixture in
tests/conftest.py's `client`, per the existing integration tests)."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from auth import get_features, get_plan, has_feature, has_plan, require_feature, require_plan


def test_get_plan_returns_raw_claim_or_none():
    assert get_plan({"pla": "u:pro"}) == "u:pro"
    assert get_plan({}) is None


def test_get_features_returns_list_or_empty():
    assert get_features({"fea": ["u:priority_support"]}) == ["u:priority_support"]
    assert get_features({}) == []
    assert get_features({"fea": None}) == []


def test_has_plan_matches_slug_regardless_of_scope_prefix():
    assert has_plan({"pla": "u:pro"}, "pro") is True
    assert has_plan({"pla": "o:pro"}, "pro") is True
    assert has_plan({"pla": "u:free"}, "pro") is False
    assert has_plan({}, "pro") is False


def test_has_feature_matches_slug_regardless_of_scope_prefix():
    claims = {"fea": ["u:priority_support", "o:sso"]}
    assert has_feature(claims, "priority_support") is True
    assert has_feature(claims, "sso") is True
    assert has_feature(claims, "nonexistent") is False
    assert has_feature({}, "sso") is False


def test_has_plan_unprefixed_claim_still_matches():
    # If a token ever carries an unscoped plan string, still match on it directly.
    assert has_plan({"pla": "pro"}, "pro") is True


# ---------------------------------------------------------------------------
# Gating dependencies — verified against a real (tiny) FastAPI app + TestClient,
# not just called as bare functions, so the Depends()/HTTPException wiring is real.
# ---------------------------------------------------------------------------


def _make_app(claims: dict) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_claims(request, call_next):
        request.state.claims = claims
        return await call_next(request)

    @app.get("/pro-only", dependencies=[Depends(require_plan("pro"))])
    def pro_only():
        return {"ok": True}

    @app.get("/sso-only", dependencies=[Depends(require_feature("sso"))])
    def sso_only():
        return {"ok": True}

    return app


def test_require_plan_allows_matching_plan():
    client = TestClient(_make_app({"pla": "u:pro"}))
    assert client.get("/pro-only").status_code == 200


def test_require_plan_403s_on_wrong_plan():
    client = TestClient(_make_app({"pla": "u:free"}))
    resp = client.get("/pro-only")
    assert resp.status_code == 403
    assert "pro" in resp.json()["detail"]


def test_require_feature_allows_matching_feature():
    client = TestClient(_make_app({"fea": ["o:sso"]}))
    assert client.get("/sso-only").status_code == 200


def test_require_feature_403s_without_feature():
    client = TestClient(_make_app({"fea": []}))
    assert client.get("/sso-only").status_code == 403


# ---------------------------------------------------------------------------
# CORS preflight regression — browsers never attach Authorization to an OPTIONS
# preflight request, so gating OPTIONS the same as real requests permanently 401s
# every cross-origin authenticated call the frontend makes. Verified against the
# real app + real auth_middleware, not a toy app, since this is a middleware-wiring
# bug, not a pure-function one.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cors_preflight_is_never_gated_by_auth():
    import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as unauthenticated:
        resp = await unauthenticated.options(
            "/api/settings/aws",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )

    assert resp.status_code != 401


@pytest.mark.asyncio
async def test_real_request_without_token_is_still_401():
    """The OPTIONS bypass above must not weaken auth on the actual request."""
    import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as unauthenticated:
        resp = await unauthenticated.get("/api/settings/aws")

    assert resp.status_code == 401
