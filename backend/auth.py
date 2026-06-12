"""
Clerk JWT verification for FastAPI.

Validates Bearer tokens from the frontend Clerk session.
Extracts user_id (Clerk 'sub' claim) and stores it in request.state.
"""

import os
import logging

import jwt
from jwt import PyJWKClient
from fastapi import Request
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
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or expired token"},
        )

    return await call_next(request)
