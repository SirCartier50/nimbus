import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import get_or_create_user, get_user_settings
from db.deps import get_db
from db.models import UserSettings
from utils.aws_role import assume_role, generate_external_id

router = APIRouter()

# The IAM identity Nimbus's backend runs as — the CloudFormation template's trust
# policy allows this principal (plus the caller's own external_id condition) to
# assume the role the user creates in their account. See
# infra/nimbus-cross-account-role.yaml.
NIMBUS_PRINCIPAL_ARN = os.getenv(
    "NIMBUS_PRINCIPAL_ARN", "arn:aws:iam::804306814230:user/botouser"
)


class AWSRoleConnection(BaseModel):
    role_arn: str


class GitHubConfig(BaseModel):
    repo_url: str


async def _get_or_create_settings(db: AsyncSession, user_id) -> UserSettings:
    settings = await get_user_settings(db, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
    return settings


@router.get("/settings/aws")
async def get_aws_status(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    settings = await _get_or_create_settings(db, user.id)

    # The external_id must exist and be stable before the user deploys the
    # CloudFormation stack (it goes into the stack's trust-policy condition), so
    # generate it lazily on first view rather than only at connect time.
    if not settings.aws_external_id:
        settings.aws_external_id = generate_external_id()
        await db.commit()

    return {
        "connected": bool(settings.aws_role_arn),
        "role_arn": settings.aws_role_arn,
        "external_id": settings.aws_external_id,
        "nimbus_principal_arn": NIMBUS_PRINCIPAL_ARN,
        "region": os.getenv("AWS_REGION", "us-east-1"),
    }


@router.post("/settings/aws")
async def connect_aws_role(body: AWSRoleConnection, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    settings = await _get_or_create_settings(db, user.id)

    if not settings.aws_external_id:
        settings.aws_external_id = generate_external_id()

    try:
        session = assume_role(body.role_arn, settings.aws_external_id, session_name=f"nimbus-verify-{user.id}")
        identity = session.client("sts").get_caller_identity()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Unable to assume that role: {e}")

    settings.aws_role_arn = body.role_arn
    await db.commit()

    return {
        "connected": True,
        "account_id": identity["Account"],
        "arn": identity["Arn"],
        "region": os.getenv("AWS_REGION", "us-east-1"),
    }


@router.get("/settings/github")
async def get_github_status(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    settings = await get_user_settings(db, user.id)
    connected = bool(settings and settings.github_repo_url)
    return {
        "connected": connected,
        "repo_url": settings.github_repo_url if connected else None,
    }


@router.post("/settings/github")
async def set_github_repo(config: GitHubConfig, request: Request, db: AsyncSession = Depends(get_db)):
    if not config.repo_url.startswith("https://github.com/"):
        raise HTTPException(status_code=400, detail="Please provide a valid GitHub repository URL")

    user = await get_or_create_user(db, request.state.user_id)
    settings = await _get_or_create_settings(db, user.id)
    settings.github_repo_url = config.repo_url
    await db.commit()

    return {"connected": True, "repo_url": config.repo_url}


@router.delete("/settings/github")
async def unlink_github_repo(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    settings = await get_user_settings(db, user.id)
    if settings and settings.github_repo_url:
        settings.github_repo_url = None
        await db.commit()
    return {"connected": False, "repo_url": None}
