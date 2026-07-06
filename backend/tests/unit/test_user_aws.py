"""get_user_boto3_session — get_user_settings/assume_role mocked, no real DB/AWS."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from utils.user_aws import get_user_boto3_session


@pytest.mark.asyncio
async def test_returns_none_when_no_settings_row():
    with patch("utils.user_aws.get_user_settings", new=AsyncMock(return_value=None)):
        result = await get_user_boto3_session(db=object(), user_id=uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_settings_exist_but_no_role_connected():
    settings = SimpleNamespace(aws_role_arn=None, aws_external_id="ext-123")
    with patch("utils.user_aws.get_user_settings", new=AsyncMock(return_value=settings)):
        result = await get_user_boto3_session(db=object(), user_id=uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_assumes_role_when_connected():
    user_id = uuid.uuid4()
    settings = SimpleNamespace(aws_role_arn="arn:aws:iam::123:role/Foo", aws_external_id="ext-123")
    fake_session = object()

    with patch("utils.user_aws.get_user_settings", new=AsyncMock(return_value=settings)), \
         patch("utils.user_aws.assume_role", return_value=fake_session) as mocked_assume:
        result = await get_user_boto3_session(db=object(), user_id=user_id)

    assert result is fake_session
    mocked_assume.assert_called_once_with(
        "arn:aws:iam::123:role/Foo", "ext-123", session_name=f"nimbus-{user_id}"
    )
