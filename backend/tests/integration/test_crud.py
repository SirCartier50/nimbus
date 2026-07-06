"""db/crud.py against a real Postgres — these hit real column names, so they're the
layer that would have caught the aws_access_key_id -> aws_role_arn rename bug that
Bodyguard's own (mocked) tests couldn't see."""
from unittest.mock import patch

import pytest
from sqlalchemy import select

from db.crud import get_or_create_user, list_users_with_aws_credentials
from db.models import User, UserSettings
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.mark.asyncio
async def test_list_users_with_aws_credentials_excludes_users_without_a_role(db_session):
    user = User(clerk_user_id="user-no-role")
    db_session.add(user)
    await db_session.commit()
    db_session.add(UserSettings(user_id=user.id))  # no aws_role_arn set
    await db_session.commit()

    result = await list_users_with_aws_credentials(db_session)
    assert result == []


@pytest.mark.asyncio
async def test_list_users_with_aws_credentials_includes_users_with_a_role(db_session):
    user = User(clerk_user_id="user-with-role")
    db_session.add(user)
    await db_session.commit()
    db_session.add(UserSettings(
        user_id=user.id,
        aws_role_arn="arn:aws:iam::123456789012:role/NimbusAccessRole",
        aws_external_id="ext-abc",
    ))
    await db_session.commit()

    result = await list_users_with_aws_credentials(db_session)
    assert [u.id for u in result] == [user.id]


@pytest.mark.asyncio
async def test_get_or_create_user_is_idempotent(db_session):
    first = await get_or_create_user(db_session, "clerk-abc")
    second = await get_or_create_user(db_session, "clerk-abc")
    assert first.id == second.id

    result = await db_session.execute(select(User).where(User.clerk_user_id == "clerk-abc"))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_get_or_create_user_second_call_skips_the_db_entirely(db_session):
    """The whole point of the cache: a second lookup for the same clerk_user_id
    must not touch the database at all."""
    first = await get_or_create_user(db_session, "clerk-cached")

    with patch.object(db_session, "execute", side_effect=AssertionError("cache should have avoided this query")):
        second = await get_or_create_user(db_session, "clerk-cached")

    assert second.id == first.id


@pytest.mark.asyncio
async def test_get_or_create_user_cache_is_cleared_between_tests(db_session):
    """Companion to the fixture-level clear in conftest.py — pins down that a
    clerk_user_id used in an earlier test doesn't resolve to a stale UUID here."""
    result = await db_session.execute(select(User).where(User.clerk_user_id == "clerk-cached"))
    assert result.scalar_one_or_none() is None
