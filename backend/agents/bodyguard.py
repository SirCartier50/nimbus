import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from db.crud import list_users_with_aws_credentials
from db.engine import async_session_local
from utils.aws_clients import get_cloudwatch_client, get_ec2_client, get_sts_client
from utils.tool_use import run_tool_loop
from utils.user_aws import get_user_boto3_session

logger = logging.getLogger("bodyguard")

CHECK_INTERVAL = 300
IPV4_COST_PER_HOUR = 0.005
EBS_GP2_COST_PER_GB_MONTH = 0.10
EBS_GP3_COST_PER_GB_MONTH = 0.08

# Bodyguard patrols every user's AWS account independently, each with its own
# decrypted boto3 session and its own isolated state slot — alerts/logs for one
# user must never leak into another user's dashboard. `state` is keyed by
# str(user_id); `_daemon_active` is the one piece of truly global, non-user
# data (whether the background loop itself is running at all).
state: dict[str, dict] = {}
_daemon_active = False


def _new_user_state() -> dict:
    return {
        "last_check": None,
        "instances_stopped": 0,
        "logs": [],
        "alerts": [],
        "sub_resources": {
            "volumes": [],
            "elastic_ips": [],
            "snapshots": [],
        },
    }


def _get_user_state(user_id: str) -> dict:
    if user_id not in state:
        state[user_id] = _new_user_state()
    return state[user_id]


# ---------------------------------------------------------------------------
# State helpers — operate on one user's state slot, never the module globally
# ---------------------------------------------------------------------------


def _log(user_state: dict, msg: str, level: str = "info"):
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level, "message": msg}
    user_state["logs"].append(entry)
    if len(user_state["logs"]) > 200:
        user_state["logs"] = user_state["logs"][-100:]
    getattr(logger, level, logger.info)(msg)


def _alert(user_state: dict, msg: str, severity: str = "warning"):
    user_state["alerts"].append({
        "id": f"alert-{int(time.time() * 1000)}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": msg,
        "severity": severity,
        "read": False,
    })
    if len(user_state["alerts"]) > 100:
        user_state["alerts"] = user_state["alerts"][-50:]


# ---------------------------------------------------------------------------
# Tool handlers — the bodyguard AI calls these, scoped to one user's session
# ---------------------------------------------------------------------------


def _handle_list_running_instances(params: dict, session=None) -> dict:
    ec2 = get_ec2_client(session)
    resp = ec2.describe_instances(
        Filters=[
            {"Name": "instance-state-name", "Values": ["running"]},
            {"Name": "tag:ManagedBy", "Values": ["Nimbus"]},
        ]
    )
    instances = []
    for r in resp.get("Reservations", []):
        for inst in r.get("Instances", []):
            name = next(
                (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                inst["InstanceId"],
            )
            instances.append({
                "instance_id": inst["InstanceId"],
                "name": name,
                "instance_type": inst.get("InstanceType"),
                "public_ip": inst.get("PublicIpAddress"),
                "launch_time": inst["LaunchTime"].isoformat() if inst.get("LaunchTime") else None,
                "managed_by_nimbus": True,
                "is_free_tier": inst.get("InstanceType") in ("t2.micro", "t3.micro"),
            })
    return {"instances": instances, "count": len(instances)}


def _handle_get_cpu_metrics(params: dict, session=None) -> dict:
    cw = get_cloudwatch_client(session)
    instance_id = params["instance_id"]
    minutes = params.get("minutes", 30)

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)

    metrics = cw.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start,
        EndTime=end,
        Period=300,
        Statistics=["Average"],
    )
    points = metrics.get("Datapoints", [])
    if not points:
        return {"instance_id": instance_id, "avg_cpu": None, "datapoints": 0, "note": "No data — instance may be new"}

    avg = sum(p["Average"] for p in points) / len(points)
    return {
        "instance_id": instance_id,
        "avg_cpu": round(avg, 2),
        "datapoints": len(points),
        "period_minutes": minutes,
    }


def _handle_check_ebs_volumes(params: dict, session=None, user_state: dict = None) -> dict:
    ec2 = get_ec2_client(session)
    vols = ec2.describe_volumes().get("Volumes", [])
    volumes = []
    for vol in vols:
        size_gb = vol.get("Size", 0)
        vol_type = vol.get("VolumeType", "gp2")
        attachments = vol.get("Attachments", [])
        cost_per_month = size_gb * (EBS_GP3_COST_PER_GB_MONTH if vol_type == "gp3" else EBS_GP2_COST_PER_GB_MONTH)

        volumes.append({
            "volume_id": vol["VolumeId"],
            "size_gb": size_gb,
            "type": vol_type,
            "state": vol.get("State", "unknown"),
            "attached_to": attachments[0]["InstanceId"] if attachments else None,
            "cost_per_month": round(cost_per_month, 2),
        })

    if user_state is not None:
        user_state["sub_resources"]["volumes"] = volumes
    orphaned = [v for v in volumes if not v["attached_to"]]
    return {
        "volumes": volumes,
        "total": len(volumes),
        "orphaned_count": len(orphaned),
        "orphaned_monthly_cost": round(sum(v["cost_per_month"] for v in orphaned), 2),
    }


def _handle_check_elastic_ips(params: dict, session=None, user_state: dict = None) -> dict:
    ec2 = get_ec2_client(session)
    eips = ec2.describe_addresses().get("Addresses", [])
    result = []
    for eip in eips:
        associated = eip.get("InstanceId")
        result.append({
            "allocation_id": eip.get("AllocationId", ""),
            "public_ip": eip.get("PublicIp", ""),
            "attached_to": associated,
            "cost_per_month": 0.0 if associated else round(IPV4_COST_PER_HOUR * 730, 2),
        })
    if user_state is not None:
        user_state["sub_resources"]["elastic_ips"] = result
    return {"elastic_ips": result, "total": len(result)}


def _handle_check_snapshots(params: dict, session=None, user_state: dict = None) -> dict:
    ec2 = get_ec2_client(session)
    account_id = get_sts_client(session).get_caller_identity()["Account"]
    snaps = ec2.describe_snapshots(OwnerIds=[account_id]).get("Snapshots", [])
    result = []
    for snap in snaps:
        size_gb = snap.get("VolumeSize", 0)
        result.append({
            "snapshot_id": snap["SnapshotId"],
            "size_gb": size_gb,
            "state": snap.get("State", "unknown"),
            "cost_per_month": round(size_gb * 0.05, 2),
        })
    if user_state is not None:
        user_state["sub_resources"]["snapshots"] = result
    total_cost = sum(s["cost_per_month"] for s in result)
    return {"snapshots": result, "total": len(result), "total_monthly_cost": round(total_cost, 2)}


def _handle_stop_instance(params: dict, session=None, user_state: dict = None) -> dict:
    ec2 = get_ec2_client(session)
    instance_id = params["instance_id"]
    reason = params.get("reason", "Stopped by Nimbus Bodyguard")
    ec2.stop_instances(InstanceIds=[instance_id])
    if user_state is not None:
        user_state["instances_stopped"] += 1
        _log(user_state, f"Stopped instance {instance_id}: {reason}", "warning")
    return {"success": True, "instance_id": instance_id, "message": f"Instance stopped: {reason}"}


def _handle_create_alert(params: dict, user_state: dict = None) -> dict:
    message = params["message"]
    severity = params.get("severity", "warning")
    if user_state is not None:
        _alert(user_state, message, severity)
        _log(user_state, f"Alert created ({severity}): {message}")
    return {"success": True, "message": "Alert created"}


def _handle_log_finding(params: dict, user_state: dict = None) -> dict:
    message = params["message"]
    level = params.get("level", "info")
    if user_state is not None:
        _log(user_state, message, level)
    return {"success": True}


def _build_handlers(session, user_state: dict) -> dict:
    """Bind session + user_state per patrol call via closures — never globals —
    so concurrent patrols of different users' accounts can't bleed into each other."""
    return {
        "list_running_instances": lambda p: _handle_list_running_instances(p, session),
        "get_cpu_metrics": lambda p: _handle_get_cpu_metrics(p, session),
        "check_ebs_volumes": lambda p: _handle_check_ebs_volumes(p, session, user_state),
        "check_elastic_ips": lambda p: _handle_check_elastic_ips(p, session, user_state),
        "check_snapshots": lambda p: _handle_check_snapshots(p, session, user_state),
        "stop_instance": lambda p: _handle_stop_instance(p, session, user_state),
        "create_alert": lambda p: _handle_create_alert(p, user_state),
        "log_finding": lambda p: _handle_log_finding(p, user_state),
    }


# ---------------------------------------------------------------------------
# Tool config for Bedrock
# ---------------------------------------------------------------------------

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "list_running_instances",
                "description": "List all running EC2 instances with their type, IP, and whether they are free tier.",
                "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
            }
        },
        {
            "toolSpec": {
                "name": "get_cpu_metrics",
                "description": "Get average CPU utilization for an EC2 instance over a time window.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "instance_id": {"type": "string", "description": "EC2 instance ID"},
                            "minutes": {"type": "number", "description": "Time window in minutes (default 30)"},
                        },
                        "required": ["instance_id"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "check_ebs_volumes",
                "description": "List all EBS volumes, find orphaned (unattached) ones and their costs.",
                "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
            }
        },
        {
            "toolSpec": {
                "name": "check_elastic_ips",
                "description": "List all Elastic IPs and find unassociated ones that cost money.",
                "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
            }
        },
        {
            "toolSpec": {
                "name": "check_snapshots",
                "description": "List all EBS snapshots and their storage costs.",
                "inputSchema": {"json": {"type": "object", "properties": {}, "required": []}},
            }
        },
        {
            "toolSpec": {
                "name": "stop_instance",
                "description": "Stop a running EC2 instance to save costs. Only use after confirming it is idle.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "instance_id": {"type": "string", "description": "EC2 instance ID to stop"},
                            "reason": {"type": "string", "description": "Why this instance is being stopped"},
                        },
                        "required": ["instance_id", "reason"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "create_alert",
                "description": "Create a user-visible alert about a finding or action taken.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "Alert message for the user"},
                            "severity": {"type": "string", "description": "info, warning, or critical"},
                        },
                        "required": ["message"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "log_finding",
                "description": "Log an observation or finding from your patrol.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "What you observed"},
                            "level": {"type": "string", "description": "info, warning, or error"},
                        },
                        "required": ["message"],
                    }
                },
            }
        },
    ]
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

BODYGUARD_PROMPT = """You are Nimbus Bodyguard, an AI security and cost-optimization agent for AWS.

Your job is to patrol the user's AWS environment, find problems, and take action when needed.

PATROL PROCEDURE:
1. List all running instances
2. For each running instance, check its CPU utilization
3. Check for orphaned EBS volumes, unassociated Elastic IPs, and snapshots
4. Log your findings and create alerts for anything the user should know about

DECISION RULES:
- If an instance has avg CPU below 5% for 30+ minutes AND has at least 3 data points, stop it and create an alert explaining why
- If an instance is new (no CPU data yet), log it but do NOT stop it
- If you find orphaned EBS volumes or unassociated Elastic IPs, create a warning alert with the cost
- If multiple free-tier instances are running simultaneously, alert about faster free-tier burn
- If any non-free-tier instances are running, alert about the cost

SAFETY RULES:
- NEVER terminate instances, only stop them
- Always create an alert BEFORE stopping an instance
- Always provide a reason when stopping an instance
- If unsure whether to stop, create a warning alert instead and let the user decide
- Be conservative — it is better to warn than to accidentally stop something important

Be efficient with your tool calls. Start by listing instances, then only check CPU for instances that are running."""

# ---------------------------------------------------------------------------
# Background loop — one daemon task, patrolling every connected user's AWS
# account each cycle with that user's own decrypted credentials
# ---------------------------------------------------------------------------


async def _bodyguard_loop():
    logger.info("Bodyguard daemon started")

    while _daemon_active:
        try:
            async with async_session_local() as db:
                users = await list_users_with_aws_credentials(db)
                for user in users:
                    user_id = str(user.id)
                    user_state = _get_user_state(user_id)
                    user_state["last_check"] = datetime.now(timezone.utc).isoformat()
                    try:
                        session = await get_user_boto3_session(db, user.id)
                        if session is None:
                            continue
                        # Run the AI agent in a thread to avoid blocking the event loop
                        await asyncio.to_thread(_run_patrol, session, user_state)
                    except Exception as e:
                        _log(user_state, f"Patrol error: {e}", "error")
        except Exception as e:
            logger.error(f"Bodyguard loop error enumerating users: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


def _run_patrol(session, user_state: dict):
    """Run one patrol cycle for one user's AWS account using the AI agent."""
    try:
        handlers = _build_handlers(session, user_state)
        run_tool_loop(
            system_prompt=BODYGUARD_PROMPT,
            messages=[{"role": "user", "content": [{"text": "Run your patrol. Check all running instances and resources."}]}],
            tool_config=TOOL_CONFIG,
            tool_handlers=handlers,
            max_iterations=10,
        )
    except Exception as e:
        _log(user_state, f"AI patrol failed, running basic checks: {e}", "error")
        _fallback_patrol(session, user_state)


def _fallback_patrol(session, user_state: dict):
    """Basic non-AI patrol in case Bedrock is unavailable."""
    try:
        instances = _handle_list_running_instances({}, session)
        _log(user_state, f"Fallback patrol: {instances['count']} running instances")
        for inst in instances.get("instances", []):
            if not inst["is_free_tier"]:
                _alert(
                    user_state,
                    f"Non-free-tier instance '{inst['name']}' ({inst['instance_type']}) is running.",
                    "warning",
                )
    except Exception as e:
        _log(user_state, f"Fallback patrol error: {e}", "error")


def start_bodyguard():
    global _daemon_active
    _daemon_active = True
    loop = asyncio.get_event_loop()
    loop.create_task(_bodyguard_loop())


def stop_bodyguard():
    global _daemon_active
    _daemon_active = False
    logger.info("Bodyguard agent stopped")


# ---------------------------------------------------------------------------
# Public status API — every call is scoped to one user's state slot
# ---------------------------------------------------------------------------


def get_status(user_id: str) -> dict:
    user_state = _get_user_state(user_id)
    return {
        "running": _daemon_active,
        "last_check": user_state["last_check"],
        "instances_stopped_total": user_state["instances_stopped"],
        "recent_logs": user_state["logs"][-20:],
        "unread_alerts": [a for a in user_state["alerts"] if not a["read"]],
        "all_alerts": user_state["alerts"][-20:],
        "sub_resources": user_state["sub_resources"],
    }


def get_alerts(user_id: str) -> list:
    return _get_user_state(user_id)["alerts"]


def mark_alert_read(user_id: str, alert_id: str):
    user_state = _get_user_state(user_id)
    for a in user_state["alerts"]:
        if a["id"] == alert_id:
            a["read"] = True
            break
