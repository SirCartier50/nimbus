import uuid
from typing import Optional

import boto3
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import get_user_settings
from utils.aws_role import assume_role


async def get_user_boto3_session(db: AsyncSession, user_id: uuid.UUID) -> Optional[boto3.Session]:
    """Assume the user's connected IAM role and return a boto3 Session backed by
    temporary credentials (STS AssumeRole — see utils/aws_role.py).

    Returns None if the user hasn't connected an AWS role yet — callers should pass
    that through to the client getters, which fall back to process env vars.
    """
    settings = await get_user_settings(db, user_id)
    if not settings or not settings.aws_role_arn:
        return None
    return assume_role(settings.aws_role_arn, settings.aws_external_id, session_name=f"nimbus-{user_id}")
