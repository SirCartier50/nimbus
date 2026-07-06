"""STS AssumeRole provider — boto3 STS client mocked, no real AWS calls. Note: this
verifies the wiring (params sent, caching, error propagation) with a fake STS
response; it cannot prove a real cross-account trust policy actually works — that
needs two real AWS accounts, which isn't available in this environment."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from utils import aws_role


@pytest.fixture(autouse=True)
def _clear_cache():
    aws_role.clear_cache()
    yield
    aws_role.clear_cache()


def _sts_response(expires_in_seconds=3600):
    return {
        "Credentials": {
            "AccessKeyId": "ASIA_TEST",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
            "Expiration": datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds),
        }
    }


def _patched_sts(response_or_side_effect):
    sts_mock = MagicMock()
    if isinstance(response_or_side_effect, (list, Exception)):
        sts_mock.assume_role.side_effect = response_or_side_effect
    else:
        sts_mock.assume_role.return_value = response_or_side_effect
    session_mock = MagicMock()
    session_mock.client.return_value = sts_mock
    return sts_mock, patch.object(aws_role, "get_boto3_session", return_value=session_mock)


def test_generate_external_id_returns_unique_values():
    a = aws_role.generate_external_id()
    b = aws_role.generate_external_id()
    assert a != b and len(a) > 0


def test_assume_role_calls_sts_with_correct_params():
    sts_mock, patcher = _patched_sts(_sts_response())
    with patcher:
        aws_role.assume_role("arn:aws:iam::123:role/Foo", "ext-123", session_name="nimbus-test")

    sts_mock.assume_role.assert_called_once_with(
        RoleArn="arn:aws:iam::123:role/Foo",
        RoleSessionName="nimbus-test",
        ExternalId="ext-123",
    )


def test_assume_role_returns_session_with_temporary_credentials():
    sts_mock, patcher = _patched_sts(_sts_response())
    with patcher:
        result = aws_role.assume_role("arn:aws:iam::123:role/Foo", "ext-123", region="eu-west-1")

    creds = result.get_credentials()
    assert creds.access_key == "ASIA_TEST"
    assert creds.secret_key == "secret"
    assert creds.token == "token"
    assert result.region_name == "eu-west-1"


def test_assume_role_caches_until_near_expiry():
    sts_mock, patcher = _patched_sts(_sts_response(expires_in_seconds=3600))
    with patcher:
        first = aws_role.assume_role("arn:aws:iam::123:role/Foo", "ext-123")
        second = aws_role.assume_role("arn:aws:iam::123:role/Foo", "ext-123")

    assert sts_mock.assume_role.call_count == 1
    assert first is second


def test_assume_role_refreshes_once_near_expiry():
    sts_mock, patcher = _patched_sts([_sts_response(expires_in_seconds=-10), _sts_response(expires_in_seconds=3600)])
    with patcher:
        aws_role.assume_role("arn:aws:iam::123:role/Foo", "ext-123")
        aws_role.assume_role("arn:aws:iam::123:role/Foo", "ext-123")

    assert sts_mock.assume_role.call_count == 2


def test_assume_role_caches_separately_per_role_and_external_id():
    sts_mock, patcher = _patched_sts(_sts_response())
    with patcher:
        aws_role.assume_role("arn:aws:iam::123:role/Foo", "ext-A")
        aws_role.assume_role("arn:aws:iam::123:role/Foo", "ext-B")

    assert sts_mock.assume_role.call_count == 2


def test_assume_role_propagates_sts_errors():
    _, patcher = _patched_sts(Exception("AccessDenied: trust policy does not match"))
    with patcher, pytest.raises(Exception, match="AccessDenied"):
        aws_role.assume_role("arn:aws:iam::123:role/Foo", "wrong-ext-id")
