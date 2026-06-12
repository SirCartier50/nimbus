import json
import os

from utils.aws_clients import (
    get_ec2_client,
    get_s3_client,
    get_dynamodb_client,
    get_lambda_client,
    get_sts_client,
)
from utils.tool_use import run_tool_loop

# ---------------------------------------------------------------------------
# Tool definitions — read-only AWS inspection tools
# ---------------------------------------------------------------------------

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "list_ec2_instances",
                "description": "List all EC2 instances (optionally filter by state). Returns instance ID, name, type, state, public IP, and launch time.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "state": {
                                "type": "string",
                                "description": "Filter by instance state: running, stopped, terminated, or all. Default: all",
                            }
                        },
                        "required": [],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "list_s3_buckets",
                "description": "List all S3 buckets in the account with their names and creation dates.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "list_dynamodb_tables",
                "description": "List all DynamoDB tables with their status, item count, and size.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "list_lambda_functions",
                "description": "List all Lambda functions with their runtime, memory, and last modified date.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "get_account_info",
                "description": "Get the current AWS account ID, region, and caller identity.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    }
                },
            }
        },
    ]
}

# ---------------------------------------------------------------------------
# Tool handler implementations
# ---------------------------------------------------------------------------


def _handle_list_ec2(params: dict) -> dict:
    ec2 = get_ec2_client()
    filters = []
    state = params.get("state", "all")
    if state and state != "all":
        filters.append({"Name": "instance-state-name", "Values": [state]})

    resp = ec2.describe_instances(Filters=filters if filters else [])
    instances = []
    for r in resp.get("Reservations", []):
        for inst in r.get("Instances", []):
            if inst["State"]["Name"] == "terminated":
                continue
            name = next(
                (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                inst["InstanceId"],
            )
            managed_by = next(
                (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "ManagedBy"),
                None,
            )
            instances.append({
                "instance_id": inst["InstanceId"],
                "name": name,
                "instance_type": inst.get("InstanceType"),
                "state": inst["State"]["Name"],
                "public_ip": inst.get("PublicIpAddress"),
                "launch_time": inst["LaunchTime"].isoformat() if inst.get("LaunchTime") else None,
                "managed_by_nimbus": managed_by == "Nimbus",
            })
    return {"instances": instances, "count": len(instances)}


def _handle_list_s3(params: dict) -> dict:
    s3 = get_s3_client()
    resp = s3.list_buckets()
    buckets = []
    for b in resp.get("Buckets", []):
        name = b["Name"]
        managed_by_nimbus = False
        try:
            tags = s3.get_bucket_tagging(Bucket=name)
            tag_map = {t["Key"]: t["Value"] for t in tags.get("TagSet", [])}
            managed_by_nimbus = tag_map.get("ManagedBy") == "Nimbus"
        except Exception:
            pass
        buckets.append({
            "name": name,
            "created": b["CreationDate"].isoformat() if b.get("CreationDate") else None,
            "managed_by_nimbus": managed_by_nimbus,
        })
    return {"buckets": buckets, "count": len(buckets)}


def _handle_list_dynamodb(params: dict) -> dict:
    dynamo = get_dynamodb_client()
    table_names = dynamo.list_tables().get("TableNames", [])
    tables = []
    for tname in table_names:
        try:
            desc = dynamo.describe_table(TableName=tname)["Table"]
            tags_resp = dynamo.list_tags_of_resource(ResourceArn=desc["TableArn"])
            tag_map = {t["Key"]: t["Value"] for t in tags_resp.get("Tags", [])}
            tables.append({
                "name": tname,
                "status": desc.get("TableStatus"),
                "item_count": desc.get("ItemCount", 0),
                "size_bytes": desc.get("TableSizeBytes", 0),
                "managed_by_nimbus": tag_map.get("ManagedBy") == "Nimbus",
            })
        except Exception:
            tables.append({"name": tname, "status": "unknown"})
    return {"tables": tables, "count": len(tables)}


def _handle_list_lambda(params: dict) -> dict:
    lc = get_lambda_client()
    fns = lc.list_functions().get("Functions", [])
    functions = []
    for fn in fns:
        try:
            tags = lc.list_tags(Resource=fn["FunctionArn"]).get("Tags", {})
        except Exception:
            tags = {}
        functions.append({
            "name": fn["FunctionName"],
            "runtime": fn.get("Runtime"),
            "memory_mb": fn.get("MemorySize"),
            "last_modified": fn.get("LastModified"),
            "managed_by_nimbus": tags.get("ManagedBy") == "Nimbus",
        })
    return {"functions": functions, "count": len(functions)}


def _handle_get_account_info(params: dict) -> dict:
    sts = get_sts_client()
    identity = sts.get_caller_identity()
    return {
        "account_id": identity["Account"],
        "arn": identity["Arn"],
        "region": os.getenv("AWS_REGION", "us-east-1"),
    }


TOOL_HANDLERS = {
    "list_ec2_instances": _handle_list_ec2,
    "list_s3_buckets": _handle_list_s3,
    "list_dynamodb_tables": _handle_list_dynamodb,
    "list_lambda_functions": _handle_list_lambda,
    "get_account_info": _handle_get_account_info,
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

BASE_PROMPT = """You are Nimbus Architect, an expert AWS infrastructure agent.

You have two modes:

## MODE 1: Conversational (answering questions, showing resources)
When the user asks a question or wants to see their resources, use your tools to look up the information and respond conversationally. Do NOT output a JSON plan. Just answer their question directly.

Examples: "show me my S3 buckets", "how many EC2 instances do I have?", "what is Lambda?", "am I using free tier?"

## MODE 2: Planning (deploying infrastructure)
When the user wants to CREATE, MODIFY, or DELETE AWS resources, respond with a natural language explanation followed by a JSON plan block.

The JSON plan MUST be on its own line, wrapped in <nimbus-plan> tags:

<nimbus-plan>
{{"explanation": "...", "plan": [...], "cost_warning": "...", "estimated_monthly_cost": "..."}}
</nimbus-plan>

Plan actions you can use:
- create_ec2: params: name, instance_type, security_group_description
- create_s3: params: bucket_name
- create_dynamodb: params: table_name, partition_key, sort_key (optional)
- create_lambda: params: function_name, runtime, description
- stop_ec2: params: instance_id
- terminate_ec2: params: instance_id
- delete_s3: params: bucket_name
- delete_dynamodb: params: table_name
- delete_lambda: params: function_name

Each plan step: {{"step": 1, "action": "...", "params": {{...}}, "description": "..."}}

YOUR AUDIENCE: Beginners to AWS. Explain every service simply.
- EC2 = virtual server, S3 = cloud storage, DynamoDB = database, Lambda = serverless function
- Always include cost estimates
- Use simple analogies when helpful

{free_tier_clause}

IMPORTANT RULES:
- Always use your tools to check current state BEFORE planning (e.g., check if a resource already exists)
- Make bucket names globally unique by appending random characters
- For destructive actions (terminate, delete), clearly warn the user what will be lost
"""

FREE_TIER_CLAUSE = """STRICT FREE-TIER MODE IS ON.
Only recommend free-tier eligible configurations:
- EC2: ONLY t2.micro or t3.micro
- NEVER recommend RDS, Aurora, Redshift, ElastiCache, NAT Gateways, OpenSearch, ECS, EKS, or Fargate
- If the request cannot be done within free tier, explain what is and isn't possible."""

FLEXIBLE_CLAUSE = """Free-tier mode is OFF. You may recommend any service or instance type.
Still prefer cost-effective options and be transparent about costs."""


def _build_system_prompt(free_tier_mode: bool = True) -> str:
    clause = FREE_TIER_CLAUSE if free_tier_mode else FLEXIBLE_CLAUSE
    return BASE_PROMPT.format(free_tier_clause=clause)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_architect(user_request: str, conversation_history: list = None, free_tier_mode: bool = True) -> dict:
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": [{"text": user_request}]})

    system_prompt = _build_system_prompt(free_tier_mode)

    result = run_tool_loop(
        system_prompt=system_prompt,
        messages=messages,
        tool_config=TOOL_CONFIG,
        tool_handlers=TOOL_HANDLERS,
    )

    text = result["text"]

    # Check if the response contains a plan
    plan = None
    if "<nimbus-plan>" in text and "</nimbus-plan>" in text:
        try:
            plan_start = text.index("<nimbus-plan>") + len("<nimbus-plan>")
            plan_end = text.index("</nimbus-plan>")
            plan_json = text[plan_start:plan_end].strip()
            plan = json.loads(plan_json)
            # Remove the plan tags from the display text
            display_text = text[:text.index("<nimbus-plan>")].strip()
            if text.index("</nimbus-plan>") + len("</nimbus-plan>") < len(text):
                display_text += "\n" + text[text.index("</nimbus-plan>") + len("</nimbus-plan>"):].strip()
        except (json.JSONDecodeError, ValueError):
            display_text = text
            plan = None
    else:
        display_text = text

    return {
        "success": True,
        "text": display_text,
        "plan": plan,
        "messages": result["messages"],
    }
