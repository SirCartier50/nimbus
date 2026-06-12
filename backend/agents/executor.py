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
from utils.tool_use import run_tool_loop

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


def _ensure_lambda_role() -> str:
    iam = get_iam_client()
    sts = get_sts_client()
    account_id = sts.get_caller_identity()["Account"]
    role_name = "nimbus-lambda-role"
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

    try:
        iam.get_role(RoleName=role_name)
    except iam.exceptions.NoSuchEntityException:
        trust = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        })
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


# ---------------------------------------------------------------------------
# Tool handlers — called by the AI via tool use
# ---------------------------------------------------------------------------

_free_tier_mode = True  # set per execution


def _handle_create_ec2(params: dict) -> dict:
    ec2 = get_ec2_client()
    name = params.get("name", f"nimbus-{uuid.uuid4().hex[:6]}")
    instance_type = params.get("instance_type", "t2.micro")
    ami_id = params.get("ami_id") or _get_latest_ami(ec2)

    if _free_tier_mode and instance_type not in FREE_TIER_TYPES:
        instance_type = "t2.micro"

    sg_id = _ensure_security_group(ec2, params.get("security_group_description", "Nimbus managed"))

    resp = ec2.run_instances(
        ImageId=ami_id,
        InstanceType=instance_type,
        MinCount=1,
        MaxCount=1,
        SecurityGroupIds=[sg_id],
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": name}] + NIMBUS_TAG,
        }],
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


def _handle_create_s3(params: dict) -> dict:
    s3 = get_s3_client()
    region = os.getenv("AWS_REGION", "us-east-1")
    bucket_name = params.get("bucket_name", f"nimbus-{uuid.uuid4().hex[:8]}")

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


def _handle_create_dynamodb(params: dict) -> dict:
    dynamo = get_dynamodb_client()
    table_name = params.get("table_name", f"nimbus-table-{uuid.uuid4().hex[:6]}")
    pk = params.get("partition_key", "id")
    sk = params.get("sort_key")

    key_schema = [{"AttributeName": pk, "KeyType": "HASH"}]
    attr_defs = [{"AttributeName": pk, "AttributeType": "S"}]
    if sk:
        key_schema.append({"AttributeName": sk, "KeyType": "RANGE"})
        attr_defs.append({"AttributeName": sk, "AttributeType": "S"})

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


def _handle_create_lambda(params: dict) -> dict:
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


def _handle_stop_ec2(params: dict) -> dict:
    ec2 = get_ec2_client()
    instance_id = params["instance_id"]
    ec2.stop_instances(InstanceIds=[instance_id])
    return {
        "success": True,
        "resource_type": "ec2",
        "resource_id": instance_id,
        "message": f"EC2 instance '{instance_id}' is stopping",
    }


def _handle_terminate_ec2(params: dict) -> dict:
    ec2 = get_ec2_client()
    instance_id = params["instance_id"]
    ec2.terminate_instances(InstanceIds=[instance_id])
    return {
        "success": True,
        "resource_type": "ec2",
        "resource_id": instance_id,
        "message": f"EC2 instance '{instance_id}' is terminating",
    }


def _handle_delete_s3(params: dict) -> dict:
    s3 = get_s3_client()
    bucket_name = params["bucket_name"]
    # Empty the bucket first
    try:
        objects = s3.list_objects_v2(Bucket=bucket_name).get("Contents", [])
        if objects:
            s3.delete_objects(
                Bucket=bucket_name,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
            )
    except Exception:
        pass
    s3.delete_bucket(Bucket=bucket_name)
    return {
        "success": True,
        "resource_type": "s3",
        "resource_id": bucket_name,
        "message": f"S3 bucket '{bucket_name}' deleted",
    }


def _handle_delete_dynamodb(params: dict) -> dict:
    dynamo = get_dynamodb_client()
    table_name = params["table_name"]
    dynamo.delete_table(TableName=table_name)
    return {
        "success": True,
        "resource_type": "dynamodb",
        "resource_id": table_name,
        "message": f"DynamoDB table '{table_name}' deleted",
    }


def _handle_delete_lambda(params: dict) -> dict:
    lc = get_lambda_client()
    function_name = params["function_name"]
    lc.delete_function(FunctionName=function_name)
    return {
        "success": True,
        "resource_type": "lambda",
        "resource_id": function_name,
        "message": f"Lambda function '{function_name}' deleted",
    }


def _handle_list_ec2(params: dict) -> dict:
    ec2 = get_ec2_client()
    resp = ec2.describe_instances()
    instances = []
    for r in resp.get("Reservations", []):
        for inst in r.get("Instances", []):
            if inst["State"]["Name"] == "terminated":
                continue
            name = next(
                (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                inst["InstanceId"],
            )
            instances.append({
                "instance_id": inst["InstanceId"],
                "name": name,
                "state": inst["State"]["Name"],
                "type": inst.get("InstanceType"),
            })
    return {"instances": instances}


def _handle_list_s3(params: dict) -> dict:
    s3 = get_s3_client()
    resp = s3.list_buckets()
    return {"buckets": [b["Name"] for b in resp.get("Buckets", [])]}


# ---------------------------------------------------------------------------
# Tool definitions for Bedrock
# ---------------------------------------------------------------------------

CREATE_TOOLS = [
    {
        "toolSpec": {
            "name": "create_ec2_instance",
            "description": "Launch a new EC2 instance. Returns the instance ID and state.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name tag for the instance"},
                        "instance_type": {"type": "string", "description": "EC2 instance type, e.g. t2.micro"},
                        "ami_id": {"type": "string", "description": "AMI ID. Leave empty for latest Amazon Linux 2."},
                        "security_group_description": {"type": "string", "description": "Description for security group"},
                    },
                    "required": ["name"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "create_s3_bucket",
            "description": "Create a new S3 bucket. Bucket names must be globally unique.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "bucket_name": {"type": "string", "description": "Globally unique bucket name"},
                    },
                    "required": ["bucket_name"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "create_dynamodb_table",
            "description": "Create a new DynamoDB table with on-demand billing.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "table_name": {"type": "string", "description": "Table name"},
                        "partition_key": {"type": "string", "description": "Partition key attribute name"},
                        "sort_key": {"type": "string", "description": "Optional sort key attribute name"},
                    },
                    "required": ["table_name", "partition_key"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "create_lambda_function",
            "description": "Create a new Lambda function with a hello-world handler.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "function_name": {"type": "string", "description": "Function name"},
                        "runtime": {"type": "string", "description": "Runtime, e.g. python3.11"},
                        "description": {"type": "string", "description": "Function description"},
                    },
                    "required": ["function_name"],
                }
            },
        }
    },
]

DESTRUCTIVE_TOOLS = [
    {
        "toolSpec": {
            "name": "stop_ec2_instance",
            "description": "Stop a running EC2 instance. The instance can be started again later.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "instance_id": {"type": "string", "description": "EC2 instance ID"},
                    },
                    "required": ["instance_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "terminate_ec2_instance",
            "description": "Permanently terminate an EC2 instance. This cannot be undone.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "instance_id": {"type": "string", "description": "EC2 instance ID"},
                    },
                    "required": ["instance_id"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "delete_s3_bucket",
            "description": "Delete an S3 bucket and all its contents. This cannot be undone.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "bucket_name": {"type": "string", "description": "Bucket name to delete"},
                    },
                    "required": ["bucket_name"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "delete_dynamodb_table",
            "description": "Delete a DynamoDB table and all its data. This cannot be undone.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "table_name": {"type": "string", "description": "Table name to delete"},
                    },
                    "required": ["table_name"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "delete_lambda_function",
            "description": "Delete a Lambda function. This cannot be undone.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "function_name": {"type": "string", "description": "Function name to delete"},
                    },
                    "required": ["function_name"],
                }
            },
        }
    },
]

READ_TOOLS = [
    {
        "toolSpec": {
            "name": "list_ec2_instances",
            "description": "List EC2 instances to verify state after operations.",
            "inputSchema": {
                "json": {"type": "object", "properties": {}, "required": []}
            },
        }
    },
    {
        "toolSpec": {
            "name": "list_s3_buckets",
            "description": "List S3 buckets to verify operations.",
            "inputSchema": {
                "json": {"type": "object", "properties": {}, "required": []}
            },
        }
    },
]

CREATE_HANDLERS = {
    "create_ec2_instance": _handle_create_ec2,
    "create_s3_bucket": _handle_create_s3,
    "create_dynamodb_table": _handle_create_dynamodb,
    "create_lambda_function": _handle_create_lambda,
    "list_ec2_instances": _handle_list_ec2,
    "list_s3_buckets": _handle_list_s3,
}

DESTRUCTIVE_HANDLERS = {
    "stop_ec2_instance": _handle_stop_ec2,
    "terminate_ec2_instance": _handle_terminate_ec2,
    "delete_s3_bucket": _handle_delete_s3,
    "delete_dynamodb_table": _handle_delete_dynamodb,
    "delete_lambda_function": _handle_delete_lambda,
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

EXECUTOR_PROMPT = """You are Nimbus Executor, an AI agent that deploys and manages AWS infrastructure.

You receive a plan from the Nimbus Architect and execute it step by step using your tools.

RULES:
1. Execute each step in order
2. After each tool call, check the result for success or failure
3. If a step fails, report the error and continue with the remaining steps
4. After all steps, provide a summary of what succeeded and what failed
5. Use your read tools (list_ec2_instances, list_s3_buckets) to verify resources were created if needed

Your response should be a clear summary like:
- What was created/modified/deleted
- Any errors that occurred
- The resource IDs of created resources

Keep it concise. The user is a beginner — explain any errors in simple terms."""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_executor(plan: dict, free_tier_mode: bool = True, allow_destructive: bool = False) -> dict:
    global _free_tier_mode
    _free_tier_mode = free_tier_mode

    # Build tool config based on what's allowed
    tools = list(CREATE_TOOLS) + list(READ_TOOLS)
    handlers = dict(CREATE_HANDLERS)

    if allow_destructive:
        tools.extend(DESTRUCTIVE_TOOLS)
        handlers.update(DESTRUCTIVE_HANDLERS)

    tool_config = {"tools": tools}

    plan_text = json.dumps(plan, indent=2)
    messages = [
        {"role": "user", "content": [{"text": f"Execute this infrastructure plan:\n\n{plan_text}"}]}
    ]

    result = run_tool_loop(
        system_prompt=EXECUTOR_PROMPT,
        messages=messages,
        tool_config=tool_config,
        tool_handlers=handlers,
    )

    # Collect all tool results from the message history for the response
    execution_results = []
    for msg in result["messages"]:
        if msg.get("role") == "user":
            for block in msg.get("content", []):
                if isinstance(block, dict) and "toolResult" in block:
                    tr = block["toolResult"]
                    if tr.get("content"):
                        for content in tr["content"]:
                            if "json" in content:
                                data = content["json"]
                                if isinstance(data, dict) and "success" in data:
                                    execution_results.append(data)

    return {
        "text": result["text"],
        "results": execution_results,
    }


# Keep backward compatibility for file_generator
def execute_plan(plan: dict, free_tier_mode: bool = True) -> list:
    result = run_executor(plan, free_tier_mode=free_tier_mode)
    return result["results"]
