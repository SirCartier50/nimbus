"""STS AssumeRole — the cross-account credential path that replaces stored access
keys. Nimbus's own service identity (the env-level AWS creds — see
aws_clients.get_boto3_session) calls sts:AssumeRole into a role the USER deploys in
their own account (see infra/nimbus-cross-account-role.yaml), scoped by a per-user
ExternalId for confused-deputy protection. This is the AWS-recommended "temporary
security credentials" model: nothing long-lived is stored for the user at all, and a
leaked temporary credential expires on its own within the hour.
"""
import json
import logging
import os
import time
import uuid

import boto3

from utils.aws_clients import get_sts_client
from utils.redis_client import get_sync_redis

logger = logging.getLogger("aws_role")

# STS AssumeRole's default session duration (no MaxSessionDuration override on the
# role) is 1 hour; refresh a bit early to avoid edge-of-expiry failures mid-request.
_REFRESH_BUFFER_SECONDS = 60

# L1: in-memory cache of (role_arn, external_id) -> (boto3.Session, expiry_epoch).
# A boto3.Session isn't serializable, so each process keeps its own. L2 (when
# REDIS_URL is set) holds the raw temporary credentials as JSON with a TTL that
# ends before the creds expire, so N workers share one AssumeRole per user-hour
# instead of one each. Redis errors are treated as cache misses — STS is the
# source of truth either way.
_cache: dict[tuple[str, str], tuple[boto3.Session, float]] = {}


def _redis_key(role_arn: str, external_id: str) -> str:
    return f"nimbus:sts:{role_arn}:{external_id}"


def _session_from_creds(access_key_id: str, secret_access_key: str, session_token: str, region: str = None) -> boto3.Session:
    return boto3.Session(
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        aws_session_token=session_token,
        region_name=region or os.getenv("AWS_REGION", "us-east-1"),
    )


def generate_external_id() -> str:
    """A fresh, unique external_id for a user connecting AWS. Not a secret — AWS's
    own guidance is that an external_id only needs to be unique per external party,
    not kept confidential — but random/unguessable is still good practice."""
    return uuid.uuid4().hex


def assume_role(role_arn: str, external_id: str, session_name: str = "nimbus", region: str = None) -> boto3.Session:
    """Return a boto3 Session backed by temporary credentials for `role_arn`,
    reusing cached credentials until they're close to expiring. Raises whatever
    boto3/STS raises (e.g. AccessDenied on a wrong role_arn/external_id, or a trust
    policy that doesn't match) — callers should catch and surface a clear message,
    not swallow it."""
    key = (role_arn, external_id)
    cached = _cache.get(key)
    if cached and cached[1] - _REFRESH_BUFFER_SECONDS > time.time():
        return cached[0]

    redis = get_sync_redis()
    if redis is not None:
        try:
            raw = redis.get(_redis_key(role_arn, external_id))
            if raw:
                data = json.loads(raw)
                if data["expiration"] - _REFRESH_BUFFER_SECONDS > time.time():
                    session = _session_from_creds(
                        data["access_key_id"], data["secret_access_key"], data["session_token"], region
                    )
                    _cache[key] = (session, data["expiration"])
                    return session
        except Exception as e:
            logger.warning("Redis STS-cache read failed (%s) — assuming a fresh role", e)

    sts = get_sts_client()
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
        ExternalId=external_id,
    )
    creds = response["Credentials"]
    expiration = creds["Expiration"].timestamp()
    session = _session_from_creds(
        creds["AccessKeyId"], creds["SecretAccessKey"], creds["SessionToken"], region
    )
    _cache[key] = (session, expiration)

    if redis is not None:
        ttl = int(expiration - time.time() - _REFRESH_BUFFER_SECONDS)
        if ttl > 0:
            try:
                redis.set(
                    _redis_key(role_arn, external_id),
                    json.dumps({
                        "access_key_id": creds["AccessKeyId"],
                        "secret_access_key": creds["SecretAccessKey"],
                        "session_token": creds["SessionToken"],
                        "expiration": expiration,
                    }),
                    ex=ttl,
                )
            except Exception as e:
                logger.warning("Redis STS-cache write failed (%s) — continuing without it", e)

    return session


def clear_cache() -> None:
    """Test/ops hook — drop all cached temporary credentials."""
    _cache.clear()
