import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, UserSettings

# clerk_user_id -> internal user id. Every authenticated request calls
# get_or_create_user() at least once just to resolve this mapping before doing
# its own real query — that's a second full Supabase round-trip (measured
# ~200-280ms each) on top of the endpoint's actual work, for a mapping that's
# immutable once a user exists. Cache it in-process; same single-instance
# tradeoff already accepted elsewhere in this codebase (Bodyguard state,
# utils.aws_role's STS session cache) — not durable across a restart or a
# multi-worker deploy, revisit alongside those if that changes.
_user_id_cache: dict[str, uuid.UUID] = {}


def clear_user_cache() -> None:
    """Test hook — drop all cached clerk_user_id -> id mappings."""
    _user_id_cache.clear()


async def get_user_settings(db: AsyncSession, user_id: uuid.UUID) -> UserSettings | None:
    result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    return result.scalar_one_or_none()


async def list_users_with_aws_credentials(db: AsyncSession) -> list[User]:
    """Users who've connected an AWS role (STS AssumeRole) — i.e. Bodyguard/executor
    can build a session for them via utils.user_aws.get_user_boto3_session."""
    result = await db.execute(
        select(User).join(UserSettings).where(UserSettings.aws_role_arn.is_not(None))
    )
    return list(result.scalars().all())


async def get_or_create_user(db: AsyncSession, clerk_user_id: str) -> User:
    cached_id = _user_id_cache.get(clerk_user_id)
    if cached_id is not None:
        # Every caller only ever reads `.id` off the returned object (checked
        # across every route/agent that calls this) — a detached, never-persisted
        # instance is safe here, no lazy-loaded relationship is ever touched.
        return User(id=cached_id, clerk_user_id=clerk_user_id)

    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        _user_id_cache[clerk_user_id] = user.id
        return user

    user = User(clerk_user_id=clerk_user_id)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a concurrent request creating the same user.
        await db.rollback()
        result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise
    else:
        await db.refresh(user)
    _user_id_cache[clerk_user_id] = user.id
    return user
