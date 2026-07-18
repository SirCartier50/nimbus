"""Shared Redis access (PROD-3). Everything here is optional infrastructure:
when REDIS_URL is unset, every getter returns None and callers fall back to
their in-process implementation — identical behavior to the pre-Redis codebase,
which is exactly what single-instance dev/test runs use.

What lives in Redis and why:
  - rate-limit token buckets (ratelimit.py): the only state that actively
    misbehaves at N workers (each worker granting its own full budget)
  - STS temporary credentials (utils/aws_role.py): saves an AssumeRole round
    trip per process per user-hour; values expire on their own
  - dashboard snapshots (routes/dashboard.py): shares the 8s TTL cache across
    workers so the frontend poll stays cheap regardless of which worker serves it

Redis being DOWN must never take the API down: callers treat any Redis error as
a cache miss / fall back to local state and log at warning, once per incident
kind, not per request.
"""
import logging
import os

logger = logging.getLogger("redis_client")

_async_client = None
_sync_client = None

_CONNECT_KW = dict(
    decode_responses=True,
    socket_timeout=2,
    socket_connect_timeout=2,
    # A blipped connection should retry on the next request, not poison the pool.
    retry_on_timeout=True,
    health_check_interval=30,
)


def redis_url() -> str | None:
    return os.getenv("REDIS_URL") or None


def get_async_redis():
    """redis.asyncio client, or None when Redis isn't configured."""
    global _async_client
    url = redis_url()
    if not url:
        return None
    if _async_client is None:
        import redis.asyncio as aioredis

        _async_client = aioredis.from_url(url, **_CONNECT_KW)
    return _async_client


def get_sync_redis():
    """Blocking client for sync call sites (boto3/STS code paths run in threads),
    or None when Redis isn't configured."""
    global _sync_client
    url = redis_url()
    if not url:
        return None
    if _sync_client is None:
        import redis

        _sync_client = redis.Redis.from_url(url, **_CONNECT_KW)
    return _sync_client


def reset_clients() -> None:
    """Test hook — forget cached clients so a changed REDIS_URL takes effect."""
    global _async_client, _sync_client
    _async_client = None
    _sync_client = None
