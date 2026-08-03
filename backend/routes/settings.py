import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import KNOWN_PROVIDERS, MODEL_DEFAULTS, operator_key_configured
from db.crud import get_or_create_user, get_user_settings
from db.deps import get_db
from db.models import UserSettings
from utils.aws_clients import get_sts_client
from utils.aws_role import assume_role, generate_external_id
from utils.secret_box import SecretBoxNotConfigured, encrypt_secret

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


class ApiKeyBody(BaseModel):
    key: str = Field(..., min_length=1, max_length=512)


class ModelBody(BaseModel):
    model: str = Field(..., min_length=1, max_length=256)


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
        identity = get_sts_client(session).get_caller_identity()
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


def _key_status(provider: str, enc: dict) -> dict:
    ciphertext = enc.get(provider)
    if ciphertext:
        # Masked from the ciphertext's own length, not the plaintext's — avoids
        # decrypting just to render a status list nobody asked to reveal.
        return {"source": "user", "configured": True, "masked": f"····{ciphertext[-4:]}"}
    if operator_key_configured(provider):
        return {"source": "operator", "configured": True, "masked": None}
    return {"source": None, "configured": False, "masked": None}


@router.get("/settings/api-keys")
async def get_api_keys(request: Request, db: AsyncSession = Depends(get_db)):
    """Per-provider status only — the plaintext key is never sent back down
    after it's stored. `source` tells the UI whether a turn on that provider
    runs on the user's own key or the shared operator one."""
    user = await get_or_create_user(db, request.state.user_id)
    settings = await get_user_settings(db, user.id)
    enc = (settings.provider_keys_enc if settings else None) or {}
    return {provider: _key_status(provider, enc) for provider in sorted(KNOWN_PROVIDERS)}


@router.put("/settings/api-keys/{provider}")
async def set_api_key(provider: str, body: ApiKeyBody, request: Request, db: AsyncSession = Depends(get_db)):
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")

    try:
        ciphertext = encrypt_secret(body.key.strip())
    except SecretBoxNotConfigured as e:
        # Fail closed rather than falling back to storing the key in plaintext.
        raise HTTPException(status_code=503, detail=str(e))

    user = await get_or_create_user(db, request.state.user_id)
    settings = await _get_or_create_settings(db, user.id)
    # Reassigned, not mutated in place — see the field comment on
    # UserSettings.provider_keys_enc for why that matters here.
    settings.provider_keys_enc = {**(settings.provider_keys_enc or {}), provider: ciphertext}
    await db.commit()

    return {provider: _key_status(provider, settings.provider_keys_enc)}


@router.delete("/settings/api-keys/{provider}")
async def delete_api_key(provider: str, request: Request, db: AsyncSession = Depends(get_db)):
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")

    user = await get_or_create_user(db, request.state.user_id)
    settings = await get_user_settings(db, user.id)
    if settings and provider in (settings.provider_keys_enc or {}):
        settings.provider_keys_enc = {k: v for k, v in settings.provider_keys_enc.items() if k != provider}
        await db.commit()
        enc = settings.provider_keys_enc
    else:
        enc = (settings.provider_keys_enc if settings else None) or {}

    return {provider: _key_status(provider, enc)}


def _model_status(provider: str, overrides: dict) -> dict:
    default = MODEL_DEFAULTS[provider]
    override = overrides.get(provider)
    return {"model": override or default, "is_custom": override is not None, "default": default}


@router.get("/settings/models")
async def get_models(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    settings = await get_user_settings(db, user.id)
    overrides = (settings.provider_models if settings else None) or {}
    return {provider: _model_status(provider, overrides) for provider in sorted(KNOWN_PROVIDERS)}


@router.put("/settings/models/{provider}")
async def set_model(provider: str, body: ModelBody, request: Request, db: AsyncSession = Depends(get_db)):
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")

    user = await get_or_create_user(db, request.state.user_id)
    settings = await _get_or_create_settings(db, user.id)
    # Reassigned, not mutated in place — see the field comment on
    # UserSettings.provider_models for why that matters here.
    settings.provider_models = {**(settings.provider_models or {}), provider: body.model.strip()}
    await db.commit()

    return {provider: _model_status(provider, settings.provider_models)}


@router.delete("/settings/models/{provider}")
async def reset_model(provider: str, request: Request, db: AsyncSession = Depends(get_db)):
    if provider not in KNOWN_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider}'")

    user = await get_or_create_user(db, request.state.user_id)
    settings = await get_user_settings(db, user.id)
    if settings and provider in (settings.provider_models or {}):
        settings.provider_models = {k: v for k, v in settings.provider_models.items() if k != provider}
        await db.commit()
        overrides = settings.provider_models
    else:
        overrides = (settings.provider_models if settings else None) or {}

    return {provider: _model_status(provider, overrides)}
