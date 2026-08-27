import json
import os
import re

from agents.inspection import INSPECTION_TOOL_CONFIG, build_handlers
from utils.tool_use import run_tool_loop



BASE_PROMPT = """You are Nimbus Architect, an expert AWS infrastructure agent.

You receive a FINALIZED requirements specification (the Requirements agent already
gathered it from the user) and turn it into a concrete, ordered AWS deployment plan.
You do NOT ask the user questions and you do NOT make small talk — that already
happened. Produce the plan.

First, use your tools to check the current account state where it matters (e.g.
whether a resource already exists, the account's region/identity). Then respond with
a short natural-language explanation followed by a JSON plan block.

The JSON plan MUST be on its own line, wrapped in <nimbus-plan> tags:

<nimbus-plan>
{{"explanation": "...", "plan": [...], "cost_warning": "...", "estimated_monthly_cost": "..."}}
</nimbus-plan>

Each plan step is one of:
- {{"step": 1, "action": "create", "resource_type": "...", "config": {{...}}, "description": "..."}}
- {{"step": 2, "action": "delete", "resource_type": "...", "resource_id": "...", "description": "..."}}
- {{"step": 3, "action": "stop", "resource_type": "ec2_instance", "resource_id": "...", "description": "..."}}

`resource_type` is either:
  (A) one of these 15 curated short names:
      ec2_instance, s3_bucket, rds_instance, lambda_function, vpc, subnet, security_group, ecs_cluster,
      load_balancer, api_gateway, dynamodb_table, elasticache, cloudfront, nat_gateway, iam_role; OR
  (B) for ANY other AWS resource, a CloudFormation resource type name of the form "AWS::Service::Resource"
      (e.g. "AWS::SQS::Queue", "AWS::SNS::Topic", "AWS::KMS::Key", "AWS::EFS::FileSystem").
{resource_preference_clause}
Never invent a name that is neither a curated short name nor a real "AWS::..." type.

For "create" steps, `config` depends on which kind of resource_type you used:
  - Curated short name → use the resource's REAL AWS API field names (an ec2_instance config uses
    ImageId/InstanceType/MinCount/MaxCount, not simplified names like "name"). Optional fields may be omitted
    for sensible defaults (e.g. omit ImageId to get the latest Amazon Linux 2 AMI).
  - CloudFormation type name → `config` is the CloudFormation *desired-state properties* for that type
    (e.g. AWS::SQS::Queue uses {{"QueueName": "..."}}).
Cost estimates for CloudFormation-typed resources are ROUGH (Nimbus can't price arbitrary types precisely) —
whenever you use one, add a cost_warning saying the cost is an estimate.

YOUR AUDIENCE: Beginners to AWS. Keep the explanation simple and jargon-free.
- EC2 = virtual server, S3 = cloud storage, DynamoDB = database, Lambda = serverless function
- Always include cost estimates
- Order steps so dependencies come first (e.g. VPC before subnets, subnets before EC2)

{free_tier_clause}

IMPORTANT RULES:
- Always use your tools to check current state BEFORE planning (e.g., check if a resource already exists)
- Make bucket/table/function names globally or account-wide unique by appending random characters
- For destructive actions (delete, terminate), clearly warn the user what will be lost
- The <nimbus-plan> block MUST be strictly valid JSON — no "#" or "//" comments, no trailing commas.
  If a field needs explaining, put that in the natural-language explanation, not inside the JSON.
- You PROPOSE plans; you never execute them. Nothing is created/changed until the user
  confirms this plan in the UI and a separate execution step runs it. Never say you are
  "launching"/"triggering"/"deploying" anything, and never say "stand by" — you're
  producing a plan for approval, not performing an action.
"""

# Curated-vs-generic preference (Bitter-Lesson knob, PROD/DECISIONS.md). The curated
# tools carry genuine non-model value (precise cost, free-tier enforcement, special
# actions), so "curated" stays the default. As models get better at driving the
# generic Cloud Control path, `generic` lets the product cover all of AWS without
# growing the registry — flip it only with eval evidence (see backend/evals/CHECKLIST.md).
_RESOURCE_PREFERENCE_CLAUSES = {
    "curated": (
        "PREFER the curated short names whenever one fits the need — they are best-supported "
        "(validated configs, sensible defaults, precise cost, special handling). Only reach for a "
        "CloudFormation type name for resources outside that list."
    ),
    "balanced": (
        "Use whichever fits best: a curated short name for the 15 common types, or a CloudFormation "
        "type name for anything else. Neither is preferred — choose by what the request needs."
    ),
    "generic": (
        "PREFER CloudFormation type names (AWS::Service::Resource) for breadth and consistency. Use a "
        "curated short name ONLY when you specifically need its special handling: precise cost estimates, "
        "free-tier enforcement, or actions Cloud Control can't do (stop/start EC2, empty-then-delete S3, "
        "Lambda execution-role bootstrap)."
    ),
}
DEFAULT_RESOURCE_PREFERENCE = "curated"


def _resource_preference_clause() -> str:
    pref = os.getenv("ARCHITECT_RESOURCE_PREFERENCE", DEFAULT_RESOURCE_PREFERENCE).lower()
    return _RESOURCE_PREFERENCE_CLAUSES.get(pref, _RESOURCE_PREFERENCE_CLAUSES[DEFAULT_RESOURCE_PREFERENCE])


FREE_TIER_CLAUSE = """STRICT FREE-TIER MODE IS ON.
Only recommend free-tier eligible configurations:
- ec2_instance: ONLY InstanceType t2.micro or t3.micro
- NEVER recommend rds_instance, elasticache, nat_gateway, ecs_cluster, load_balancer, or cloudfront
- This applies to CloudFormation type names too — do NOT use "AWS::..." types for paid services
  (databases, NAT gateways, load balancers, etc.) in free-tier mode.
- If the request cannot be done within free tier, explain what is and isn't possible in the explanation."""

FLEXIBLE_CLAUSE = """Free-tier mode is OFF. You may recommend any resource_type and configuration.
Still prefer cost-effective options and be transparent about costs."""


def _build_system_prompt(free_tier_mode: bool = True) -> str:
    clause = FREE_TIER_CLAUSE if free_tier_mode else FLEXIBLE_CLAUSE
    return BASE_PROMPT.format(
        free_tier_clause=clause,
        resource_preference_clause=_resource_preference_clause(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_architect(
    user_request: str,
    conversation_history: list = None,
    free_tier_mode: bool = True,
    aws_session=None,
    provider=None,
) -> dict:
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": [{"text": user_request}]})

    system_prompt = _build_system_prompt(free_tier_mode)
    handlers = build_handlers(aws_session)

    result = run_tool_loop(
        system_prompt=system_prompt,
        messages=messages,
        tool_config=INSPECTION_TOOL_CONFIG,
        tool_handlers=handlers,
        provider=provider,
    )

    display_text, plan = extract_plan(result["text"])

    return {
        "success": True,
        "text": display_text,
        "plan": plan,
        "messages": result["messages"],
    }


def _strip_json_comments(s: str) -> str:
    """Best-effort removal of `#`/`//` line comments and trailing commas from
    LLM-emitted "JSON" — despite the system prompt forbidding them, the model
    has produced blocks like `"ImageId": "ami-...", # Amazon Linux 2` (valid
    Python/YAML-ish style, invalid JSON), which used to send the whole raw
    <nimbus-plan> block to the user instead of a parsed plan. Only strips
    outside of string literals so a legit value containing "#" or "//" (an
    S3 key, a URL) survives untouched.
    """
    out = []
    in_string = False
    escaped = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if in_string:
            out.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            i += 1
            continue

        if c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif c == "#" or (c == "/" and s[i + 1 : i + 2] == "/"):
            while i < n and s[i] != "\n":
                i += 1
        else:
            out.append(c)
            i += 1

    cleaned = "".join(out)
    # Trailing commas before a closing bracket are never valid JSON either.
    return re.sub(r",(\s*[}\]])", r"\1", cleaned)


def extract_plan(text: str) -> tuple[str, dict | None]:
    """Split a model response into (display_text, plan). The model wraps a JSON
    plan in <nimbus-plan> tags inline with its natural-language explanation;
    this pulls the JSON out and strips the tags from what the user sees.
    Returns (text, None) unchanged if there's no plan block, or if the block
    is present but isn't valid JSON even after comment-stripping (the model
    hallucinated malformed tags).
    """
    if "<nimbus-plan>" not in text or "</nimbus-plan>" not in text:
        return text, None

    try:
        plan_start = text.index("<nimbus-plan>") + len("<nimbus-plan>")
        plan_end = text.index("</nimbus-plan>")
        plan_json = text[plan_start:plan_end].strip()
        try:
            plan = json.loads(plan_json)
        except json.JSONDecodeError:
            plan = json.loads(_strip_json_comments(plan_json))

        display_text = text[:text.index("<nimbus-plan>")].strip()
        tail_start = text.index("</nimbus-plan>") + len("</nimbus-plan>")
        if tail_start < len(text):
            display_text += "\n" + text[tail_start:].strip()
        return display_text, plan
    except (json.JSONDecodeError, ValueError):
        return text, None
