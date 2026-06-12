# AWS Infrastructure Agent — Project Briefing

> Drop this file into your Claude Code session to continue where we left off.

---

## What This App Is

An agentic AI app that lets non-technical users describe what they want to build on AWS in plain English, and the AI provisions it for them — without them ever touching the AWS console.

**Analogy:** Like Claude Code generating a full production codebase, but instead of the user having to manually set up Supabase or AWS themselves, this app does the infrastructure provisioning for them automatically.

---

## Current State

The user currently has:
- An **Architect Agent** — creates an infrastructure plan
- An **Executor Agent** — runs the plan via boto3/AWS API calls
- Tools provided to a Nova AI model for creating instances etc.

**Problems identified with current approach:**
- Tools are static — create the same config every time, not dynamic to user needs
- No requirements gathering — model makes assumptions from vague input
- No cost visibility before building — risk of surprise AWS bills
- No validation that resources were actually created correctly
- Heading toward an unmaintainable list of granular static tools

---

## Agreed Architecture

### Agent Pipeline (linear — no LangGraph needed)

```
User Input (vague natural language)
        │
        ▼
Requirements Agent        ← LLM agent (conversational intake)
        │
        ▼
Architect Agent           ← LLM agent (spec → AWS resource plan)
        │
        ▼
Cost & Approval Agent     ← Plain code (shows cost, waits for yes/no)
        │
        ▼
Executor Agent            ← Plain code (parallel where possible)
        │
        ▼
Validator Agent           ← Plain code (confirms resources exist/healthy)
        │
        ▼
Summary Agent             ← LLM agent (human readable output)
```

**Bodyguard** runs as a separate background daemon thread (NOT an agent).

---

## Key Design Decisions

### 1. Only 3 LLM Agents — rest is plain Python
| Component | Type | Reason |
|---|---|---|
| Requirements Agent | LLM Agent | Understands vague user input |
| Architect Agent | LLM Agent | Reasons about infrastructure design |
| Cost Approval | Plain code | Just math and a display |
| Executor | Plain code | Just API calls in order |
| Validator | Plain code | Just boto3 status checks |
| Summary Agent | LLM Agent | Formats results in plain English |
| Bodyguard | Plain code | Pure metrics logic, no reasoning needed |

### 2. Config-driven tools — NOT static granular tools
Do NOT create a tool for every AWS config option. Use 6 generic tools:

```python
create_resource(resource_type, config: dict)
get_resource_status(resource_id, resource_type)
update_resource(resource_id, config)
delete_resource(resource_id, resource_type)
list_resources(resource_type)
validate_config(resource_type, config)
```

The LLM already knows AWS API specs — let it construct the config dict dynamically. Your backend just routes and executes it.

### 3. Provider abstraction layer from day one
App will support AWS first, GCP later. Agents never talk to AWS directly — they talk to a provider interface. Adding GCP = implementing the same interface with GCP SDK.

### 4. Parallel execution in Executor
Resources with no dependencies on each other build simultaneously using asyncio. Resources with dependencies build sequentially in waves.

```
Wave 1 (parallel): VPC, S3, IAM Roles
Wave 2 (parallel): Subnets, Security Groups   ← depend on VPC
Wave 3 (parallel): EC2, RDS, Lambda           ← depend on subnets/SGs
Wave 4 (sequential): Load Balancer            ← depends on EC2
```

### 5. Plan then execute — never execute from vague input
Architect produces a full ordered JSON plan before Executor touches anything. This prevents building things in wrong order (e.g. attaching subnet before VPC exists).

---

## File Structure

```
app/
├── agents/
│   ├── requirements_agent.py     # conversational intake, one Q at a time
│   ├── architect_agent.py        # spec → ordered AWS resource plan
│   ├── cost_approval_agent.py    # cost display + user approval gate
│   ├── executor_agent.py         # parallel/sequential build with asyncio
│   ├── validator_agent.py        # confirms resources exist and are healthy
│   └── summary_agent.py          # human readable final output
├── providers/
│   ├── base_provider.py          # abstract interface (cloud agnostic)
│   ├── aws/
│   │   ├── provider.py           # boto3 implementation
│   │   ├── tools.py              # create/get/update/delete/list/validate
│   │   └── validator.py          # AWS-specific health checks
│   └── gcp/                      # empty for now, implement later
│       └── provider.py
├── bodyguard/
│   └── bodyguard.py              # background daemon, CloudWatch polling
├── prompts/
│   └── system_prompts.py         # all LLM prompts in one place
└── main.py                       # orchestrates the full pipeline
```

---

## Requirements Agent Behavior

- Asks ONE question at a time
- Always provides options/suggestions with each question
- Explains tradeoffs in plain English, no jargon
- If user doesn't know → recommend sensible default and explain why
- Builds a structured JSON spec internally as conversation progresses
- Only moves to Architect when spec is complete

**Outputs this tag when done:**
```
<REQUIREMENTS_COMPLETE>
{"intent": "...", "scale": "...", "budget_priority": "...", ...}
</REQUIREMENTS_COMPLETE>
```

**Required fields to collect:**
- What they want to build
- Expected scale/traffic
- Budget sensitivity (cost optimized vs performance)
- Region preference
- Language/runtime if relevant
- Database needs
- Storage needs
- Compliance requirements

---

## Architect Agent Output Format

```json
{
    "infrastructure_plan": [
        {
            "step": 1,
            "resource_type": "vpc",
            "config": { "CidrBlock": "10.0.0.0/16" },
            "reason": "Private network to keep resources secure",
            "estimated_monthly_cost": "$0",
            "dependencies": []
        },
        {
            "step": 2,
            "resource_type": "ec2_instance",
            "config": {
                "ImageId": "ami-0abcdef1234567890",
                "InstanceType": "t3.micro",
                "MinCount": 1,
                "MaxCount": 1
            },
            "reason": "Hosts your backend API",
            "estimated_monthly_cost": "$8.47",
            "dependencies": ["vpc"]
        }
    ]
}
```

---

## Bodyguard Behavior

Runs as a **background daemon thread** (not an LLM agent). Polls CloudWatch every 5 minutes.

**Idle thresholds:**
| Resource | Metric | Threshold | Action |
|---|---|---|---|
| EC2 Instance | CPU % | < 5% for 30 min | Stop |
| RDS Instance | Connections | 0 for 60 min | Stop |
| ElastiCache | Cache hits | 0 for 60 min | Stop |
| NAT Gateway | Bytes processed | 0 for 30 min | Delete |

- Resets idle timer if resource becomes active again
- Unregisters resource after taking action
- Registered automatically after Validator confirms resources are healthy

---

## Base Provider Interface

```python
class BaseCloudProvider(ABC):
    def create_resource(self, resource_type: str, config: dict) -> dict
    def get_resource_status(self, resource_id: str, resource_type: str) -> dict
    def update_resource(self, resource_id: str, config: dict) -> dict
    def delete_resource(self, resource_id: str, resource_type: str) -> dict
    def list_resources(self, resource_type: str) -> list
    def estimate_cost(self, plan: dict) -> dict
    def validate_config(self, resource_type: str, config: dict) -> dict
```

---

## Supported AWS Resource Types (current scope)

```python
handlers = {
    "ec2_instance",
    "s3_bucket",
    "rds_instance",
    "lambda_function",
    "vpc",
    "subnet",
    "security_group",
    "ecs_cluster",
    "load_balancer",
    "api_gateway",
    "dynamodb_table",
    "elasticache",
    "cloudfront",
    "nat_gateway",
    "iam_role"
}
```

---

## What To Build First

1. `providers/base_provider.py` — abstract interface
2. `providers/aws/provider.py` — boto3 implementation
3. `agents/requirements_agent.py` — conversational intake
4. `agents/architect_agent.py` — spec to plan
5. `agents/cost_approval_agent.py` — cost display + approval
6. `agents/executor_agent.py` — parallel build
7. `agents/validator_agent.py` — health checks
8. `agents/summary_agent.py` — output formatting
9. `bodyguard/bodyguard.py` — background cost watchdog
10. `main.py` — pipeline orchestration

---

## Key Principles To Maintain

- **Never build anything without user cost approval**
- **Never use LangGraph** — pipeline is linear, plain Python is sufficient
- **Never create static tools** — all resource creation is config-driven and dynamic
- **Agents only where reasoning is needed** — everything else is plain code
- **Provider abstraction always** — agents never import boto3 directly
- **Validate after every resource creation** — never assume AWS succeeded
- **Feed errors back to the model** — let it self-correct bad configs