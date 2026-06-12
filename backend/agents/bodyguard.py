import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from utils.aws_clients import get_cloudwatch_client, get_ec2_client, get_sts_client
from utils.tool_use import run_tool_loop

logger = logging.getLogger("bodyguard")

CHECK_INTERVAL = 300
IPV4_COST_PER_HOUR = 0.005
EBS_GP2_COST_PER_GB_MONTH = 0.10
EBS_GP3_COST_PER_GB_MONTH = 0.08

state = {
    "running": False,
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

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _log(msg: str, level: str = "info"):
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level, "message": msg}
    state["logs"].append(entry)
    if len(state["logs"]) > 200:
        state["logs"] = state["logs"][-100:]
    getattr(logger, level, logger.info)(msg)


def _alert(msg: str, severity: str = "warning"):
    state["alerts"].append({
        "id": f"alert-{int(time.time() * 1000)}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": msg,
        "severity": severity,
        "read": False,
    })
    if len(state["alerts"]) > 100:
        state["alerts"] = state["alerts"][-50:]


# ---------------------------------------------------------------------------
# Tool handlers — the bodyguard AI calls these
# ---------------------------------------------------------------------------


def _handle_list_running_instances(params: dict) -> dict:
    ec2 = get_ec2_client()
    resp = ec2.describe_instances(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    )
    instances = []
    for r in resp.get("Reservations", []):
        for inst in r.get("Instances", []):
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
                "public_ip": inst.get("PublicIpAddress"),
                "launch_time": inst["LaunchTime"].isoformat() if inst.get("LaunchTime") else None,
                "managed_by_nimbus": managed_by == "Nimbus",
                "is_free_tier": inst.get("InstanceType") in ("t2.micro", "t3.micro"),
            })
    return {"instances": instances, "count": len(instances)}


def _handle_get_cpu_metrics(params: dict) -> dict:
    cw = get_cloudwatch_client()
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


def _handle_check_ebs_volumes(params: dict) -> dict:
    ec2 = get_ec2_client()
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

    state["sub_resources"]["volumes"] = volumes
    orphaned = [v for v in volumes if not v["attached_to"]]
    return {
        "volumes": volumes,
        "total": len(volumes),
        "orphaned_count": len(orphaned),
        "orphaned_monthly_cost": round(sum(v["cost_per_month"] for v in orphaned), 2),
    }


def _handle_check_elastic_ips(params: dict) -> dict:
    ec2 = get_ec2_client()
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
    state["sub_resources"]["elastic_ips"] = result
    return {"elastic_ips": result, "total": len(result)}


def _handle_check_snapshots(params: dict) -> dict:
    ec2 = get_ec2_client()
    account_id = get_sts_client().get_caller_identity()["Account"]
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
    state["sub_resources"]["snapshots"] = result
    total_cost = sum(s["cost_per_month"] for s in result)
    return {"snapshots": result, "total": len(result), "total_monthly_cost": round(total_cost, 2)}


def _handle_stop_instance(params: dict) -> dict:
    ec2 = get_ec2_client()
    instance_id = params["instance_id"]
    reason = params.get("reason", "Stopped by Nimbus Bodyguard")
    ec2.stop_instances(InstanceIds=[instance_id])
    state["instances_stopped"] += 1
    _log(f"Stopped instance {instance_id}: {reason}", "warning")
    return {"success": True, "instance_id": instance_id, "message": f"Instance stopped: {reason}"}


def _handle_create_alert(params: dict) -> dict:
    message = params["message"]
    severity = params.get("severity", "warning")
    _alert(message, severity)
    _log(f"Alert created ({severity}): {message}")
    return {"success": True, "message": "Alert created"}


def _handle_log_finding(params: dict) -> dict:
    message = params["message"]
    level = params.get("level", "info")
    _log(message, level)
    return {"success": True}


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

TOOL_HANDLERS = {
    "list_running_instances": _handle_list_running_instances,
    "get_cpu_metrics": _handle_get_cpu_metrics,
    "check_ebs_volumes": _handle_check_ebs_volumes,
    "check_elastic_ips": _handle_check_elastic_ips,
    "check_snapshots": _handle_check_snapshots,
    "stop_instance": _handle_stop_instance,
    "create_alert": _handle_create_alert,
    "log_finding": _handle_log_finding,
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
# Background loop
# ---------------------------------------------------------------------------


async def _bodyguard_loop():
    _log("Bodyguard agent started")
    state["running"] = True

    while state["running"]:
        try:
            state["last_check"] = datetime.now(timezone.utc).isoformat()
            _log("Starting patrol...")

            # Run the AI agent in a thread to avoid blocking the event loop
            await asyncio.to_thread(_run_patrol)

            _log(f"Patrol complete. Next check in {CHECK_INTERVAL}s")
        except Exception as e:
            _log(f"Patrol error: {e}", "error")

        await asyncio.sleep(CHECK_INTERVAL)


def _run_patrol():
    """Run one patrol cycle using the AI agent."""
    try:
        run_tool_loop(
            system_prompt=BODYGUARD_PROMPT,
            messages=[{"role": "user", "content": [{"text": "Run your patrol. Check all running instances and resources."}]}],
            tool_config=TOOL_CONFIG,
            tool_handlers=TOOL_HANDLERS,
            max_iterations=10,
        )
    except Exception as e:
        _log(f"AI patrol failed, running basic checks: {e}", "error")
        _fallback_patrol()


def _fallback_patrol():
    """Basic non-AI patrol in case Bedrock is unavailable."""
    try:
        instances = _handle_list_running_instances({})
        _log(f"Fallback patrol: {instances['count']} running instances")
        for inst in instances.get("instances", []):
            if not inst["is_free_tier"]:
                _alert(
                    f"Non-free-tier instance '{inst['name']}' ({inst['instance_type']}) is running.",
                    "warning",
                )
    except Exception as e:
        _log(f"Fallback patrol error: {e}", "error")


def start_bodyguard():
    loop = asyncio.get_event_loop()
    loop.create_task(_bodyguard_loop())


def stop_bodyguard():
    state["running"] = False
    _log("Bodyguard agent stopped")


# ---------------------------------------------------------------------------
# Public status API (unchanged)
# ---------------------------------------------------------------------------


def get_status() -> dict:
    return {
        "running": state["running"],
        "last_check": state["last_check"],
        "instances_stopped_total": state["instances_stopped"],
        "recent_logs": state["logs"][-20:],
        "unread_alerts": [a for a in state["alerts"] if not a["read"]],
        "all_alerts": state["alerts"][-20:],
        "sub_resources": state["sub_resources"],
    }


def get_alerts() -> list:
    return state["alerts"]


def mark_alert_read(alert_id: str):
    for a in state["alerts"]:
        if a["id"] == alert_id:
            a["read"] = True
            break
