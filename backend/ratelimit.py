"""Per-user API rate limiting (SEC-2).

In-process token buckets keyed by (user_id, bucket). Runs as middleware *inside*
the auth middleware (registered earlier in main.py, so auth — the outermost — has
already populated request.state.user_id by the time this runs). Chat routes get a
tight budget because each request fans out to an LLM + boto3; everything else gets
a loose one that only exists to stop runaway loops.

Deliberately process-local: at one uvicorn worker this is exact, at N workers each
worker allows its own budget (N× the limit) — acceptable pre-launch. Move the
counters to Redis when PROD-3 lands; the public surface (middleware + 429 body +
Retry-After header) stays the same.
"""

import math
import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse

# requests per minute; env-overridable so ops can tune without a deploy
CHAT_PER_MINUTE = int(os.getenv("RATE_LIMIT_CHAT_PER_MINUTE", "10"))
DEFAULT_PER_MINUTE = int(os.getenv("RATE_LIMIT_DEFAULT_PER_MINUTE", "120"))

# Evict buckets idle this long so the table can't grow unbounded.
_IDLE_EVICT_SECONDS = 15 * 60
_MAX_BUCKETS = 10_000


class TokenBucket:
    __slots__ = ("capacity", "refill_per_sec", "tokens", "last")

    def __init__(self, per_minute: int, now: float):
        self.capacity = float(per_minute)
        self.refill_per_sec = per_minute / 60.0
        self.tokens = float(per_minute)
        self.last = now

    def try_consume(self, now: float) -> float:
        """Take one token. Returns 0.0 on success, else seconds until a token exists."""
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.refill_per_sec)
        self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return 0.0
        return (1.0 - self.tokens) / self.refill_per_sec


class RateLimiter:
    def __init__(self):
        self._buckets: dict[tuple[str, str], TokenBucket] = {}
        self._last_sweep = 0.0

    def check(self, user_id: str, bucket_name: str, per_minute: int) -> float:
        now = time.monotonic()
        self._maybe_sweep(now)
        key = (user_id, bucket_name)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = self._buckets[key] = TokenBucket(per_minute, now)
        return bucket.try_consume(now)

    def _maybe_sweep(self, now: float) -> None:
        if now - self._last_sweep < 60 and len(self._buckets) < _MAX_BUCKETS:
            return
        self._last_sweep = now
        stale = [k for k, b in self._buckets.items() if now - b.last > _IDLE_EVICT_SECONDS]
        for k in stale:
            del self._buckets[k]


_limiter = RateLimiter()


def _bucket_for(path: str) -> tuple[str, int]:
    if path.startswith("/api/chat"):
        return "chat", CHAT_PER_MINUTE
    return "default", DEFAULT_PER_MINUTE


async def rate_limit_middleware(request: Request, call_next):
    # Only authenticated API traffic is limited; auth (outermost) has already 401'd
    # anything without a valid token, and OPTIONS preflights sail through both.
    if not request.url.path.startswith("/api/") or request.method == "OPTIONS":
        return await call_next(request)

    user_id = getattr(request.state, "user_id", None)
    if user_id is None:  # auth was bypassed (e.g. tests mounting routes bare) — don't guess
        return await call_next(request)

    bucket_name, per_minute = _bucket_for(request.url.path)
    retry_after = _limiter.check(user_id, bucket_name, per_minute)
    if retry_after > 0:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests — please slow down and try again shortly."},
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )
    return await call_next(request)
