import os
import boto3
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()

_config = {
    "aws": {
        "access_key_id": os.getenv("AWS_ACCESS_KEY_ID", ""),
        "secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        "region": os.getenv("AWS_REGION", "us-east-1"),
        "connected": bool(os.getenv("AWS_ACCESS_KEY_ID")),
    },
    "github": {
        "repo_url": "",
        "connected": False,
    },
}


class AWSCredentials(BaseModel):
    access_key_id: str
    secret_access_key: str
    region: Optional[str] = "us-east-1"


@router.get("/settings/aws")
async def get_aws_status():
    return {
        "connected": _config["aws"]["connected"],
        "region": _config["aws"]["region"],
        "masked_key": (
            _config["aws"]["access_key_id"][:4] + "****" + _config["aws"]["access_key_id"][-4:]
            if _config["aws"]["connected"]
            else None
        ),
    }


@router.post("/settings/aws")
async def set_aws_credentials(creds: AWSCredentials):
    try:
        sts = boto3.client(
            "sts",
            aws_access_key_id=creds.access_key_id,
            aws_secret_access_key=creds.secret_access_key,
            region_name=creds.region,
        )
        identity = sts.get_caller_identity()

        _config["aws"]["access_key_id"] = creds.access_key_id
        _config["aws"]["secret_access_key"] = creds.secret_access_key
        _config["aws"]["region"] = creds.region or "us-east-1"
        _config["aws"]["connected"] = True

        os.environ["AWS_ACCESS_KEY_ID"] = creds.access_key_id
        os.environ["AWS_SECRET_ACCESS_KEY"] = creds.secret_access_key
        os.environ["AWS_REGION"] = creds.region or "us-east-1"

        return {
            "connected": True,
            "account_id": identity["Account"],
            "arn": identity["Arn"],
            "region": creds.region,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid AWS credentials: {str(e)}")


class GitHubConfig(BaseModel):
    repo_url: str


@router.get("/settings/github")
async def get_github_status():
    return {
        "connected": _config["github"]["connected"],
        "repo_url": _config["github"]["repo_url"] if _config["github"]["connected"] else None,
    }


@router.post("/settings/github")
async def set_github_repo(config: GitHubConfig):
    if not config.repo_url.startswith("https://github.com/"):
        raise HTTPException(status_code=400, detail="Please provide a valid GitHub repository URL")

    _config["github"]["repo_url"] = config.repo_url
    _config["github"]["connected"] = True

    return {"connected": True, "repo_url": config.repo_url}
