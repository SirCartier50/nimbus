"""Per-user daily spend guardrail (PROD-5).

The per-minute rate limiter stops bursts, but 10 turns/min sustained is still
14,400 LLM turns per user per day — a real bill. This caps total chat TURNS per
user per UTC day (turns are the unit that costs money: each one fans out to an
LLM plus boto3 work; token-level accounting would need provider usage APIs and
buys little at this scale).

Counters live in Redis when configured (one shared budget across workers,
self-expiring keys); otherwise in-process, per worker — same fail-open posture
as the rate limiter: a Redis blip must degrade the guardrail, not down the API.
"""
import logging
import os
import time
from datetime import datetime, timezone

from utils.redis_client import get_async_redis

logger = logging.getLogger("budget")

# Key lifetime after first turn of the day: 25h, so a key created at 23:59 UTC
# still exists at 00:58 for stragglers reading it, then Redis reaps it.
_KEY_TTL_SECONDS = 25 * 3600

# In-process fallback: {(user_id, yyyymmdd): count}. Old days are dropped
# whenever a new day starts, so the dict stays one-day sized.
_local_counts: dict[tuple[str, str], int] = {}
_local_day = ""


def daily_turn_limit() -> int:
    """Read at call time (not import) so tests and ops can tune without reloads.
    0 disables the cap entirely."""
    return int(os.getenv("DAILY_TURN_LIMIT", "100"))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    return max(1, 86400 - (now.hour * 3600 + now.minute * 60 + now.second))


async def consume_daily_turn(user_id: str) -> tuple[bool, int, int]:
    """Spend one turn from the user's daily budget. Returns
    (allowed, used_today, limit). Denied attempts are not counted."""
    limit = daily_turn_limit()
    if limit <= 0:
        return True, 0, 0

    day = _today()
    redis = get_async_redis()
    if redis is not None:
        try:
            key = f"nimbus:budget:{user_id}:{day}"
            used = await redis.incr(key)
            if used == 1:
                await redis.expire(key, _KEY_TTL_SECONDS)
            if used > limit:
                await redis.decr(key)  # denied attempts don't burn budget
                return False, limit, limit
            return True, int(used), limit
        except Exception as e:
            logger.warning("Redis unavailable for budget tracking (%s) — using in-process counter", e)

    global _local_day
    if _local_day != day:
        _local_day = day
        _local_counts.clear()
    key2 = (user_id, day)
    used = _local_counts.get(key2, 0)
    if used >= limit:
        return False, used, limit
    _local_counts[key2] = used + 1
    return True, used + 1, limit


def clear_local_counts() -> None:
    """Test hook."""
    global _local_day
    _local_counts.clear()
    _local_day = ""
