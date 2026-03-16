import json
import re
import hashlib
from utils.aws_clients import get_bedrock_client

NOVA_MODEL_ID = "us.amazon.nova-lite-v1:0"
FALLBACK_MODEL_IDS = [
    "amazon.nova-2-lite-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "amazon.nova-lite-v1:0",
    "us.amazon.nova-micro-v1:0",
    "amazon.nova-micro-v1:0",
]

BASE_PROMPT = """You are Nimbus Architect, an expert AWS infrastructure planner.
You translate plain-English requests into production-ready AWS architectures.

YOUR AUDIENCE: Complete beginners to AWS and DevOps. They may not know what EC2, S3, or Lambda means.

COMMUNICATION RULES:
- In the "explanation" field, explain your plan as if talking to someone who has never used AWS.
- For EVERY service you recommend, briefly say what it is and WHY you chose it for their use case.
  Example: "An EC2 instance (a virtual server that runs 24/7) to host your web application."
- If there are alternative approaches, briefly mention them and explain why you picked this one.
- Use simple analogies when helpful (e.g., "S3 is like a hard drive in the cloud").
- Avoid jargon without explanation. If you must use a technical term, define it inline.

SERVICES YOU CAN DEPLOY:
- EC2: Virtual servers (t2.micro is free-tier eligible, 750 hrs/mo for 12 months)
- S3: Object storage (5 GB free-tier, 20k GET / 2k PUT per month)
- DynamoDB: NoSQL database (25 GB free, 25 WCU/RCU always free with PAY_PER_REQUEST)
- Lambda: Serverless functions (1M requests/mo, 400k GB-seconds always free)
- CloudWatch: Monitoring (basic metrics always free)

COST AWARENESS:
- Always include accurate cost estimates in your response.
- Clearly distinguish between free-tier eligible and paid options.
- If a user's request can be fulfilled within free tier, prefer that unless they specify otherwise.
- If it cannot, explain what will cost money and how much.

{free_tier_clause}

You receive plain-English user requests and respond ONLY with a valid JSON object — no markdown, no prose outside the JSON.

JSON schema (follow exactly):
{{
  "explanation": "<beginner-friendly explanation of what you will build, what each service is, why you chose it, and any alternatives>",
  "plan": [
    {{
      "step": 1,
      "action": "create_ec2 | create_s3 | create_dynamodb | create_lambda",
      "params": {{ <action-specific params> }},
      "description": "<beginner-friendly sentence: what this step does and why, e.g. 'Create a virtual server (EC2) to run your web app'>"
    }}
  ],
  "cost_warning": "<any cost or free-tier limits the user should know about, or empty string>",
  "estimated_monthly_cost": "<estimated cost, e.g. '$0.00 (free tier)' or '$12.50/mo'>"
}}

Params per action:
- create_ec2:      {{ "name": "str", "instance_type": "t2.micro", "security_group_description": "str" }}
- create_s3:       {{ "bucket_name": "nimbus-<something>-<random>" }}
- create_dynamodb: {{ "table_name": "str", "partition_key": "str", "sort_key": "str (optional)" }}
- create_lambda:   {{ "function_name": "str", "runtime": "python3.11", "description": "str" }}

Always make bucket names globally unique by appending a short hex suffix."""

FREE_TIER_CLAUSE = """STRICT FREE-TIER MODE IS ON.
You MUST only recommend services and configurations that are 100% free-tier eligible.
- EC2: ONLY t2.micro or t3.micro
- NEVER recommend RDS, Aurora, Redshift, ElastiCache, NAT Gateways, OpenSearch, ECS, EKS, or Fargate
- If the user asks for something that cannot be done within free tier, explain what is and isn't possible instead of proceeding."""

FLEXIBLE_CLAUSE = """Free-tier mode is OFF. You may recommend any AWS service or instance type.
Still prefer cost-effective options and always be transparent about estimated costs.
If a free-tier option can fulfill the request, mention it as an alternative."""


def _build_system_prompt(free_tier_mode: bool = True) -> str:
    clause = FREE_TIER_CLAUSE if free_tier_mode else FLEXIBLE_CLAUSE
    return BASE_PROMPT.format(free_tier_clause=clause)


def _unique_suffix(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:8]


def _smart_fallback(user_request: str, free_tier_mode: bool = True) -> dict:
    req = user_request.lower()
    suffix = _unique_suffix(user_request)

    if any(w in req for w in ["api", "rest", "backend", "server", "web app", "website"]):
        plan = {
            "explanation": (
                "I'll set up a web application for you using three AWS services. "
                "First, an EC2 instance — think of it as a virtual computer in the cloud that runs 24/7 and hosts your app. "
                "I'm using a t2.micro instance which is free for the first year (750 hours/month). "
                "Second, an S3 bucket — this is like a hard drive in the cloud where you can store files, images, and static assets. "
                "Third, a DynamoDB table — a fast, flexible NoSQL database that can handle millions of requests. "
                "The free tier gives you 25 GB of storage and enough read/write capacity for most starter apps."
            ),
            "plan": [
                {"step": 1, "action": "create_ec2", "params": {"name": "nimbus-web-server", "instance_type": "t2.micro", "security_group_description": "Allow HTTP/HTTPS traffic for web server"}, "description": "Create a virtual server (EC2 t2.micro) to run your web application — free tier eligible"},
                {"step": 2, "action": "create_s3", "params": {"bucket_name": f"nimbus-assets-{suffix}"}, "description": "Create cloud storage (S3 bucket) for static files like images, CSS, and JavaScript"},
                {"step": 3, "action": "create_dynamodb", "params": {"table_name": f"nimbus-app-data-{suffix}", "partition_key": "id"}, "description": "Create a NoSQL database (DynamoDB) to store your application data"},
            ],
            "cost_warning": "EC2 t2.micro is free for 750 hrs/month for 12 months. S3 and DynamoDB have always-free tiers." if free_tier_mode else "",
            "estimated_monthly_cost": "$0.00 (free tier)" if free_tier_mode else "$8.50/mo",
        }
    elif any(w in req for w in ["static", "landing", "portfolio", "html"]):
        plan = {
            "explanation": (
                "For a static website, you don't need a server at all. "
                "I'll create an S3 bucket configured for website hosting — it serves your HTML, CSS, and JavaScript files directly to visitors. "
                "This is the most cost-effective way to host a website on AWS, and it's completely within the free tier."
            ),
            "plan": [
                {"step": 1, "action": "create_s3", "params": {"bucket_name": f"nimbus-site-{suffix}"}, "description": "Create an S3 bucket configured for static website hosting"},
            ],
            "cost_warning": "S3 free tier: 5 GB storage, 20,000 GET requests/month, 2,000 PUT requests/month.",
            "estimated_monthly_cost": "$0.00 (free tier)",
        }
    elif any(w in req for w in ["serverless", "function", "cron", "scheduled", "lambda", "event"]):
        plan = {
            "explanation": (
                "I'll create a serverless function using AWS Lambda. "
                "Unlike a server that runs all the time, Lambda only runs when triggered — like when someone visits a URL or on a schedule. "
                "You only pay for the time your code actually runs, and the free tier gives you 1 million requests per month for free. "
                "I'll also add a DynamoDB table if your function needs to store data."
            ),
            "plan": [
                {"step": 1, "action": "create_lambda", "params": {"function_name": f"nimbus-function-{suffix}", "runtime": "python3.11", "description": "Serverless function for processing requests"}, "description": "Create a serverless function (Lambda) that runs your code on-demand without managing servers"},
                {"step": 2, "action": "create_dynamodb", "params": {"table_name": f"nimbus-function-data-{suffix}", "partition_key": "id"}, "description": "Create a database (DynamoDB) for your function to store and retrieve data"},
            ],
            "cost_warning": "Lambda free tier: 1M requests/month, 400,000 GB-seconds of compute. DynamoDB: 25 GB free.",
            "estimated_monthly_cost": "$0.00 (free tier)",
        }
    elif any(w in req for w in ["database", "store", "data", "table"]):
        plan = {
            "explanation": (
                "I'll create a DynamoDB table for your data storage needs. "
                "DynamoDB is a NoSQL database — instead of traditional rows and columns like Excel, it stores data as flexible documents. "
                "It's extremely fast, automatically scales, and the free tier is generous: 25 GB of storage with enough capacity for most applications."
            ),
            "plan": [
                {"step": 1, "action": "create_dynamodb", "params": {"table_name": f"nimbus-data-{suffix}", "partition_key": "id", "sort_key": "created_at"}, "description": "Create a NoSQL database (DynamoDB) to store your data with fast read/write performance"},
            ],
            "cost_warning": "DynamoDB always-free tier: 25 GB storage, 25 read/write capacity units.",
            "estimated_monthly_cost": "$0.00 (free tier)",
        }
    elif any(w in req for w in ["storage", "files", "upload", "bucket", "backup"]):
        plan = {
            "explanation": (
                "I'll set up an S3 bucket for file storage. "
                "S3 (Simple Storage Service) is like a cloud hard drive — you can store any type of file: documents, images, videos, backups. "
                "Files are stored redundantly across multiple data centers, so they're extremely durable. "
                "The free tier gives you 5 GB of storage."
            ),
            "plan": [
                {"step": 1, "action": "create_s3", "params": {"bucket_name": f"nimbus-storage-{suffix}"}, "description": "Create cloud storage (S3) for uploading and managing your files"},
            ],
            "cost_warning": "S3 free tier: 5 GB standard storage, 20,000 GET and 2,000 PUT requests per month.",
            "estimated_monthly_cost": "$0.00 (free tier)",
        }
    else:
        plan = {
            "explanation": (
                f"Based on your request, I'll set up a flexible infrastructure that covers the basics. "
                "An EC2 instance (virtual server) to run your application, "
                "an S3 bucket for file storage, "
                "and a DynamoDB table as your database. "
                "This gives you compute, storage, and data — the three pillars of most cloud applications. "
                "Everything is configured within the AWS free tier."
            ),
            "plan": [
                {"step": 1, "action": "create_ec2", "params": {"name": "nimbus-server", "instance_type": "t2.micro", "security_group_description": "Allow HTTP and SSH traffic"}, "description": "Create a virtual server (EC2) to run your application"},
                {"step": 2, "action": "create_s3", "params": {"bucket_name": f"nimbus-files-{suffix}"}, "description": "Create cloud storage (S3) for your files and assets"},
                {"step": 3, "action": "create_dynamodb", "params": {"table_name": f"nimbus-db-{suffix}", "partition_key": "id"}, "description": "Create a database (DynamoDB) for your application data"},
            ],
            "cost_warning": "All services configured within AWS free tier limits.",
            "estimated_monthly_cost": "$0.00 (free tier)",
        }

    raw_text = json.dumps(plan, indent=2)
    return {"success": True, "plan": plan, "raw": raw_text}


def run_architect(user_request: str, conversation_history: list = None, free_tier_mode: bool = True) -> dict:
    client = get_bedrock_client()

    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": [{"text": user_request}]})

    system_prompt = _build_system_prompt(free_tier_mode)

    model_ids = [NOVA_MODEL_ID] + FALLBACK_MODEL_IDS
    last_error = None

    for model_id in model_ids:
        try:
            response = client.converse(
                modelId=model_id,
                messages=messages,
                system=[{"text": system_prompt}],
                inferenceConfig={"maxTokens": 2048, "temperature": 0.1},
            )

            raw_text = response["output"]["message"]["content"][0]["text"].strip()
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

            plan = json.loads(raw_text)
            return {"success": True, "plan": plan, "raw": raw_text, "model": model_id}

        except json.JSONDecodeError as e:
            raw = raw_text if "raw_text" in dir() else ""
            return {"success": False, "error": f"Model returned invalid JSON: {e}", "raw": raw}
        except Exception as e:
            last_error = str(e)
            continue

    return _smart_fallback(user_request, free_tier_mode)
