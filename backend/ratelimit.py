"""Per-user API rate limiting (SEC-2, Redis-shared since PROD-3).

Token buckets keyed by (user_id, bucket). Runs as middleware *inside* the auth
middleware (registered earlier in main.py, so auth — the outermost — has already
populated request.state.user_id by the time this runs). Chat routes get a tight
budget because each request fans out to an LLM + boto3; everything else gets a
loose one that only exists to stop runaway loops.

When REDIS_URL is set the buckets live in Redis (one shared budget no matter how
many workers/replicas serve traffic), updated atomically by a Lua script. When
it isn't — or Redis errors mid-request — the in-process buckets below take over:
rate limiting FAILS OPEN to per-worker budgets rather than 500ing every request
because a cache blipped.
"""

import logging
import math
import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from utils.redis_client import get_async_redis

logger = logging.getLogger("ratelimit")

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

# Same refill math as TokenBucket.try_consume, executed atomically inside Redis
# so concurrent workers can't both spend the last token. Clock comes from the
# caller (time.time()): worker clocks are NTP-close, and a small skew only
# shifts refill timing, never corrupts the bucket.
_TOKEN_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', KEYS[1], 'tokens', 'last')
local tokens = tonumber(data[1])
local last = tonumber(data[2])
if tokens == nil then tokens = capacity end
if last == nil then last = now end
tokens = math.min(capacity, tokens + math.max(0, now - last) * refill)
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  retry = (1 - tokens) / refill
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'last', now)
redis.call('EXPIRE', KEYS[1], 900)
return tostring(retry)
"""

_redis_down_logged = False


async def _check_shared(user_id: str, bucket_name: str, per_minute: int) -> float | None:
    """Consume from the Redis-shared bucket. Returns retry-after seconds like
    RateLimiter.check, or None when Redis is unconfigured/unreachable (caller
    falls back to the in-process limiter)."""
    global _redis_down_logged
    redis = get_async_redis()
    if redis is None:
        return None
    try:
        retry = await redis.eval(
            _TOKEN_BUCKET_LUA,
            1,
            f"nimbus:rl:{bucket_name}:{user_id}",
            per_minute,
            per_minute / 60.0,
            time.time(),
        )
        _redis_down_logged = False
        return float(retry)
    except Exception as e:
        if not _redis_down_logged:
            logger.warning("Redis unavailable for rate limiting (%s) — falling back to in-process buckets", e)
            _redis_down_logged = True
        return None


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
    retry_after = await _check_shared(user_id, bucket_name, per_minute)
    if retry_after is None:
        retry_after = _limiter.check(user_id, bucket_name, per_minute)
    if retry_after > 0:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests — please slow down and try again shortly."},
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )
    return await call_next(request)
