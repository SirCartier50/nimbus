import io
import json
import os
import time
import uuid
import zipfile

from utils.aws_clients import (
    get_dynamodb_client,
    get_ec2_client,
    get_iam_client,
    get_lambda_client,
    get_s3_client,
    get_sts_client,
)

NIMBUS_TAG = [{"Key": "ManagedBy", "Value": "Nimbus"}]

FREE_TIER_TYPES = ("t2.micro", "t3.micro")


def _get_latest_ami(ec2_client) -> str:
    try:
        resp = ec2_client.describe_images(
            Owners=["amazon"],
            Filters=[
                {"Name": "name", "Values": ["amzn2-ami-hvm-*-x86_64-gp2"]},
                {"Name": "state", "Values": ["available"]},
            ],
        )
        images = sorted(resp["Images"], key=lambda x: x["CreationDate"], reverse=True)
        if images:
            return images[0]["ImageId"]
    except Exception:
        pass
    return "ami-0c55b159cbfafe1f0"


def create_ec2_instance(params: dict, free_tier_mode: bool = True) -> dict:
    ec2 = get_ec2_client()

    name = params.get("name", f"nimbus-{uuid.uuid4().hex[:6]}")
    instance_type = params.get("instance_type", "t2.micro")
    ami_id = params.get("ami_id") or _get_latest_ami(ec2)

    if free_tier_mode and instance_type not in FREE_TIER_TYPES:
        instance_type = "t2.micro"

    try:
        sg_id = _ensure_security_group(ec2, params.get("security_group_description", "Nimbus managed"))

        resp = ec2.run_instances(
            ImageId=ami_id,
            InstanceType=instance_type,
            MinCount=1,
            MaxCount=1,
            SecurityGroupIds=[sg_id],
            TagSpecifications=[
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Name", "Value": name}] + NIMBUS_TAG,
                }
            ],
        )

        inst = resp["Instances"][0]
        return {
            "success": True,
            "resource_type": "ec2",
            "resource_id": inst["InstanceId"],
            "name": name,
            "instance_type": instance_type,
            "state": inst["State"]["Name"],
            "message": f"EC2 instance '{name}' ({inst['InstanceId']}) launched",
        }
    except Exception as e:
        return {"success": False, "resource_type": "ec2", "error": str(e)}


def _ensure_security_group(ec2_client, description: str) -> str:
    resp = ec2_client.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": ["nimbus-sg"]}]
    )
    if resp["SecurityGroups"]:
        return resp["SecurityGroups"][0]["GroupId"]

    sg = ec2_client.create_security_group(
        GroupName="nimbus-sg",
        Description=description or "Nimbus security group",
    )
    sg_id = sg["GroupId"]
    ec2_client.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[
            {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            {"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
        ],
    )
    return sg_id


def create_s3_bucket(params: dict) -> dict:
    s3 = get_s3_client()
    region = os.getenv("AWS_REGION", "us-east-1")

    bucket_name = params.get("bucket_name", f"nimbus-{uuid.uuid4().hex[:8]}")

    try:
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )

        s3.put_bucket_tagging(
            Bucket=bucket_name,
            Tagging={"TagSet": NIMBUS_TAG},
        )

        return {
            "success": True,
            "resource_type": "s3",
            "resource_id": bucket_name,
            "name": bucket_name,
            "message": f"S3 bucket '{bucket_name}' created",
        }
    except Exception as e:
        return {"success": False, "resource_type": "s3", "error": str(e)}


def create_dynamodb_table(params: dict) -> dict:
    dynamo = get_dynamodb_client()

    table_name = params.get("table_name", f"nimbus-table-{uuid.uuid4().hex[:6]}")
    pk = params.get("partition_key", "id")
    sk = params.get("sort_key")

    key_schema = [{"AttributeName": pk, "KeyType": "HASH"}]
    attr_defs = [{"AttributeName": pk, "AttributeType": "S"}]

    if sk:
        key_schema.append({"AttributeName": sk, "KeyType": "RANGE"})
        attr_defs.append({"AttributeName": sk, "AttributeType": "S"})

    try:
        dynamo.create_table(
            TableName=table_name,
            KeySchema=key_schema,
            AttributeDefinitions=attr_defs,
            BillingMode="PAY_PER_REQUEST",
            Tags=NIMBUS_TAG,
        )
        return {
            "success": True,
            "resource_type": "dynamodb",
            "resource_id": table_name,
            "name": table_name,
            "message": f"DynamoDB table '{table_name}' created",
        }
    except Exception as e:
        return {"success": False, "resource_type": "dynamodb", "error": str(e)}


def create_lambda_function(params: dict) -> dict:
    lc = get_lambda_client()

    function_name = params.get("function_name", f"nimbus-fn-{uuid.uuid4().hex[:6]}")
    runtime = params.get("runtime", "python3.11")
    description = params.get("description", "Nimbus managed Lambda function")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "index.py",
            "def handler(event, context):\n    return {'statusCode': 200, 'body': 'Hello from Nimbus!'}\n",
        )
    buf.seek(0)

    try:
        role_arn = _ensure_lambda_role()

        for _ in range(6):
            try:
                lc.create_function(
                    FunctionName=function_name,
                    Runtime=runtime,
                    Role=role_arn,
                    Handler="index.handler",
                    Code={"ZipFile": buf.read()},
                    Description=description,
                    Timeout=30,
                    MemorySize=128,
                    Tags={"ManagedBy": "Nimbus"},
                )
                break
            except lc.exceptions.InvalidParameterValueException as e:
                if "role" in str(e).lower():
                    time.sleep(5)
                    buf.seek(0)
                else:
                    raise

        return {
            "success": True,
            "resource_type": "lambda",
            "resource_id": function_name,
            "name": function_name,
            "message": f"Lambda function '{function_name}' created",
        }
    except Exception as e:
        return {"success": False, "resource_type": "lambda", "error": str(e)}


def _ensure_lambda_role() -> str:
    iam = get_iam_client()
    sts = get_sts_client()
    account_id = sts.get_caller_identity()["Account"]
    role_name = "nimbus-lambda-role"
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

    try:
        iam.get_role(RoleName=role_name)
    except iam.exceptions.NoSuchEntityException:
        trust = json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "lambda.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        )
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=trust,
            Description="Nimbus Lambda execution role",
        )
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )

    return role_arn


def execute_plan(plan: dict, free_tier_mode: bool = True) -> list:
    action_map = {
        "create_ec2": lambda p: create_ec2_instance(p, free_tier_mode=free_tier_mode),
        "create_s3": create_s3_bucket,
        "create_dynamodb": create_dynamodb_table,
        "create_lambda": create_lambda_function,
    }

    results = []
    for step in plan.get("plan", []):
        action = step.get("action")
        params = step.get("params", {})

        if action in action_map:
            result = action_map[action](params)
        else:
            result = {"success": False, "error": f"Unknown action: {action}"}

        result["step"] = step.get("step")
        result["description"] = step.get("description", action)
        results.append(result)

    return results
