import os
import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

# Every AWS client in the codebase is built through make_client() so timeout and
# retry policy is uniform. Without an explicit Config, botocore's defaults allow
# a hung connection to occupy a worker thread for minutes; "standard" retry mode
# also covers more retryable error classes than the legacy default.
_BASE_CONFIG = Config(
    connect_timeout=10,
    read_timeout=60,
    retries={"max_attempts": 3, "mode": "standard"},
)
# Bedrock inference legitimately runs for minutes on a large plan — a 60s read
# timeout would kill valid requests. Fewer retries: re-running a slow LLM call
# on timeout doubles cost for little gain.
_BEDROCK_CONFIG = Config(
    connect_timeout=10,
    read_timeout=300,
    retries={"max_attempts": 2, "mode": "standard"},
)


class NoUserAWSSession(RuntimeError):
    """A user-scoped AWS client was requested without a per-user session.

    Raised instead of silently building the client from Nimbus's own operator
    credentials. Falling back there was a real privilege-escalation path: a user
    who never connected an AWS role has aws_session=None, and without this guard
    every boto3 client would resolve to the operator (botouser) account — so a
    plan would provision/delete/read resources in Nimbus's OWN account, and the
    dashboard would surface the operator's resources to any authenticated user.
    """


# The only services allowed to fall back to Nimbus's operator credentials when
# no per-user session is supplied. `sts` bootstraps every AssumeRole (that call
# IS made with the operator identity, by design); `pricing` returns public,
# account-independent list prices. Every other service operates ON a user's
# account and MUST be built from that user's assumed-role session.
_OPERATOR_CRED_SERVICES = frozenset({"sts", "pricing"})


def get_boto3_session(access_key_id: str = None, secret_access_key: str = None, region: str = None) -> boto3.Session:
    """Build a boto3 Session from explicit credentials, falling back to process env vars."""
    return boto3.Session(
        aws_access_key_id=access_key_id or os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=region or os.getenv("AWS_REGION", "us-east-1"),
    )


def make_client(service: str, session: boto3.Session = None, **kwargs):
    """Central client factory — build every boto3 client through here so the
    timeout/retry Config above applies everywhere, including clients created
    from per-user assumed-role sessions.

    Fail closed: a user-scoped service with no session must NOT silently borrow
    Nimbus's operator credentials (see NoUserAWSSession)."""
    if session is None and service not in _OPERATOR_CRED_SERVICES:
        raise NoUserAWSSession(
            f"Refusing to build a '{service}' client from Nimbus's operator "
            "credentials — no per-user AWS session was supplied. The user must "
            "connect their AWS account first."
        )
    config = _BEDROCK_CONFIG if service == "bedrock-runtime" else _BASE_CONFIG
    return (session or get_boto3_session()).client(service, config=config, **kwargs)


def get_ec2_client(session: boto3.Session = None):
    return make_client("ec2", session)


def get_bedrock_client(session: boto3.Session = None):
    return make_client("bedrock-runtime", session)


def get_cloudwatch_client(session: boto3.Session = None):
    return make_client("cloudwatch", session)


def get_dynamodb_client(session: boto3.Session = None):
    return make_client("dynamodb", session)


def get_s3_client(session: boto3.Session = None):
    return make_client("s3", session)


def get_lambda_client(session: boto3.Session = None):
    return make_client("lambda", session)


def get_iam_client(session: boto3.Session = None):
    return make_client("iam", session)


def get_sts_client(session: boto3.Session = None):
    return make_client("sts", session)
