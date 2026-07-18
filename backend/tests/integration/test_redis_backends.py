"""The Redis-backed paths (PROD-3) against a real Redis. Everything here must
also work with REDIS_URL unset — that fallback is what the rest of the suite
exercises — so these tests only cover the shared-state upgrade itself.

Opt-in like the Postgres tests: point REDIS_TEST_URL at a disposable Redis
(CI runs one as a service container) or run one on localhost:6379.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from utils import redis_client

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://localhost:6379/0")


def _redis_reachable() -> bool:
    try:
        import redis

        r = redis.Redis.from_url(REDIS_TEST_URL, socket_connect_timeout=2)
        r.ping()
        r.close()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(
    not _redis_reachable(), reason="No reachable test Redis — set REDIS_TEST_URL or run one locally"
)

pytestmark = requires_redis


@pytest.fixture
def redis_env(monkeypatch):
    """Point the app's Redis layer at the test instance, and forget any client
    built against a previous URL."""
    monkeypatch.setenv("REDIS_URL", REDIS_TEST_URL)
    redis_client.reset_clients()
    yield
    redis_client.reset_clients()


@pytest.mark.asyncio
async def test_rate_limit_bucket_is_shared_and_atomic(redis_env):
    from ratelimit import _check_shared

    user = f"user-{uuid.uuid4()}"  # fresh bucket — Redis state outlives test runs
    assert await _check_shared(user, "chat", 2) == 0.0
    assert await _check_shared(user, "chat", 2) == 0.0
    third = await _check_shared(user, "chat", 2)
    assert third is not None and third > 0.0


@pytest.mark.asyncio
async def test_rate_limit_returns_none_without_redis(monkeypatch):
    from ratelimit import _check_shared

    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset_clients()
    assert await _check_shared("anyone", "chat", 10) is None


def test_sts_credentials_are_shared_across_processes(redis_env):
    """Second process (simulated by clearing the L1 session cache) must reuse
    the Redis-cached temporary credentials instead of calling STS again."""
    from utils import aws_role

    sts = MagicMock()
    sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "AKIATEST",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
            "Expiration": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    }
    role_arn = f"arn:aws:iam::123456789012:role/nimbus-{uuid.uuid4()}"

    aws_role.clear_cache()
    with patch("utils.aws_role.get_sts_client", return_value=sts):
        first = aws_role.assume_role(role_arn, "ext-id")
        aws_role.clear_cache()  # "new process": no in-memory session
        second = aws_role.assume_role(role_arn, "ext-id")

    assert sts.assume_role.call_count == 1
    creds = second.get_credentials()
    assert creds.access_key == "AKIATEST"
    assert first.get_credentials().access_key == creds.access_key


@pytest.mark.asyncio
async def test_dashboard_cache_roundtrip_and_ttl_key(redis_env):
    from routes.dashboard import _cache_get, _cache_put

    user_id = uuid.uuid4()
    assert await _cache_get(user_id) is None

    payload = {"ec2": [], "bodyguard": {"running": False}}
    await _cache_put(user_id, payload)
    assert await _cache_get(user_id) == payload

    # Redis owns eviction: the key must carry a TTL, not live forever.
    redis = redis_client.get_async_redis()
    ttl = await redis.ttl(f"nimbus:dash:{user_id}")
    assert 0 < ttl <= 8
