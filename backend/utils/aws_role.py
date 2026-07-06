"""STS AssumeRole — the cross-account credential path that replaces stored access
keys. Nimbus's own service identity (the env-level AWS creds — see
aws_clients.get_boto3_session) calls sts:AssumeRole into a role the USER deploys in
their own account (see infra/nimbus-cross-account-role.yaml), scoped by a per-user
ExternalId for confused-deputy protection. This is the AWS-recommended "temporary
security credentials" model: nothing long-lived is stored for the user at all, and a
leaked temporary credential expires on its own within the hour.
"""
import os
import time
import uuid

import boto3

from utils.aws_clients import get_boto3_session

# STS AssumeRole's default session duration (no MaxSessionDuration override on the
# role) is 1 hour; refresh a bit early to avoid edge-of-expiry failures mid-request.
_REFRESH_BUFFER_SECONDS = 60

# In-memory cache of (role_arn, external_id) -> (boto3.Session, expiry_epoch_seconds).
# Single-process cache — same tradeoff already accepted elsewhere in this codebase
# (Bodyguard state, session history); fine at current scale, won't survive a process
# restart or a multi-worker deploy. Revisit alongside those if/when that changes.
_cache: dict[tuple[str, str], tuple[boto3.Session, float]] = {}


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

    sts = get_boto3_session().client("sts")
    response = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
        ExternalId=external_id,
    )
    creds = response["Credentials"]
    session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region or os.getenv("AWS_REGION", "us-east-1"),
    )
    _cache[key] = (session, creds["Expiration"].timestamp())
    return session


def clear_cache() -> None:
    """Test/ops hook — drop all cached temporary credentials."""
    _cache.clear()
