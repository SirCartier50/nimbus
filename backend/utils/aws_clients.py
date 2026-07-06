import os
import boto3
from dotenv import load_dotenv

load_dotenv()


def get_boto3_session(access_key_id: str = None, secret_access_key: str = None, region: str = None) -> boto3.Session:
    """Build a boto3 Session from explicit credentials, falling back to process env vars."""
    return boto3.Session(
        aws_access_key_id=access_key_id or os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=region or os.getenv("AWS_REGION", "us-east-1"),
    )


def get_ec2_client(session: boto3.Session = None):
    return (session or get_boto3_session()).client("ec2")


def get_bedrock_client(session: boto3.Session = None):
    return (session or get_boto3_session()).client("bedrock-runtime")


def get_cloudwatch_client(session: boto3.Session = None):
    return (session or get_boto3_session()).client("cloudwatch")


def get_dynamodb_client(session: boto3.Session = None):
    return (session or get_boto3_session()).client("dynamodb")


def get_s3_client(session: boto3.Session = None):
    return (session or get_boto3_session()).client("s3")


def get_lambda_client(session: boto3.Session = None):
    return (session or get_boto3_session()).client("lambda")


def get_iam_client(session: boto3.Session = None):
    return (session or get_boto3_session()).client("iam")


def get_sts_client(session: boto3.Session = None):
    return (session or get_boto3_session()).client("sts")
