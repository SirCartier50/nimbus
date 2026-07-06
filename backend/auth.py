"""
Clerk JWT verification for FastAPI.

Validates Bearer tokens from the frontend Clerk session using PyJWT + Clerk's JWKS
endpoint (RS256) — this is Clerk's own documented approach for non-JS backends, not a
stand-in for an SDK; there is no simpler/safer path to swap in here. Extracts user_id
(Clerk 'sub' claim) and the full claim set and stores both on request.state.

Billing: Clerk Billing plan/feature entitlements ride along in the same session token
as the reserved `pla` (plan) and `fea` (features) claims, e.g. pla="u:pro" for a
user-scoped plan or "o:free_org" for an org-scoped one — see has_plan()/has_feature().
"""

import os
import logging

import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("auth")

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        issuer = os.getenv("CLERK_ISSUER", "").rstrip("/")
        if not issuer:
            raise RuntimeError("CLERK_ISSUER env var is not set")
        _jwks_client = PyJWKClient(f"{issuer}/.well-known/jwks.json")
    return _jwks_client


def verify_clerk_token(token: str) -> dict:
    """Verify a Clerk JWT and return its payload."""
    client = _get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)
    issuer = os.getenv("CLERK_ISSUER", "").rstrip("/")
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        issuer=issuer,
        options={"verify_aud": False},
    )
    return payload


async def auth_middleware(request: Request, call_next):
    """FastAPI middleware that protects all /api/* routes with Clerk JWT auth."""
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    # CORS preflight requests never carry an Authorization header — browsers strip
    # credentials from OPTIONS by design — so gating them here always 401s and breaks
    # CORS for every authenticated route, regardless of middleware ordering. Let it
    # through to CORSMiddleware/the router; only the real request needs a token.
    if request.method == "OPTIONS":
        return await call_next(request)

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid Authorization header"},
        )

    token = auth_header.split(" ", 1)[1]
    try:
        payload = verify_clerk_token(token)
        request.state.user_id = payload["sub"]
        request.state.claims = payload
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or expired token"},
        )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Clerk Billing — plan/feature checks against the verified token's claims.
# ---------------------------------------------------------------------------


def _claim_slug(value: str) -> str:
    """pla/fea claim values are scope-prefixed ("u:pro", "o:free_org"). Match on the
    slug regardless of scope, the same way the frontend's has({ plan }) helper does."""
    return value.split(":", 1)[1] if ":" in value else value


def get_plan(claims: dict) -> str | None:
    """The raw `pla` claim (e.g. "u:pro"), or None if the token carries no plan."""
    return claims.get("pla")


def get_features(claims: dict) -> list[str]:
    return claims.get("fea") or []


def has_plan(claims: dict, plan: str) -> bool:
    pla = claims.get("pla")
    return bool(pla) and _claim_slug(pla) == plan


def has_feature(claims: dict, feature: str) -> bool:
    return any(_claim_slug(f) == feature for f in claims.get("fea") or [])


def require_plan(plan: str):
    """FastAPI dependency: 403s unless the caller's token carries the given plan.
    Usage: @router.post(..., dependencies=[Depends(require_plan("pro"))])"""
    def _dependency(request: Request):
        if not has_plan(request.state.claims, plan):
            raise HTTPException(status_code=403, detail=f"This requires the '{plan}' plan.")
    return _dependency


def require_feature(feature: str):
    """FastAPI dependency: 403s unless the caller's token carries the given feature.
    Usage: @router.post(..., dependencies=[Depends(require_feature("priority_support"))])"""
    def _dependency(request: Request):
        if not has_feature(request.state.claims, feature):
            raise HTTPException(status_code=403, detail=f"This requires the '{feature}' feature.")
    return _dependency
