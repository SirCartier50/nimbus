import os
import boto3
from dotenv import load_dotenv

load_dotenv()


def _creds():
    return {
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "region_name": os.getenv("AWS_REGION", "us-east-1"),
    }


def get_ec2_client():
    return boto3.client("ec2", **_creds())


def get_bedrock_client():
    return boto3.client("bedrock-runtime", **_creds())


def get_cloudwatch_client():
    return boto3.client("cloudwatch", **_creds())


def get_dynamodb_client():
    return boto3.client("dynamodb", **_creds())


def get_s3_client():
    return boto3.client("s3", **_creds())


def get_lambda_client():
    return boto3.client("lambda", **_creds())


def get_iam_client():
    return boto3.client("iam", **_creds())


def get_sts_client():
    return boto3.client("sts", **_creds())
