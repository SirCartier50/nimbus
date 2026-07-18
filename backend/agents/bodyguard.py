import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from db.crud import list_users_with_aws_credentials
from db.engine import async_session_local
from db.models import BodyguardAlert, BodyguardLog, BodyguardStatus, Deployment
from utils.aws_clients import get_cloudwatch_client, get_ec2_client, get_sts_client
from utils.user_aws import get_user_boto3_session

logger = logging.getLogger("bodyguard")

CHECK_INTERVAL = 300
IPV4_COST_PER_HOUR = 0.005
EBS_GP2_COST_PER_GB_MONTH = 0.10
EBS_GP3_COST_PER_GB_MONTH = 0.08

# Logs are diagnostic noise, not history — keep a week, then prune each cycle.
LOG_RETENTION_DAYS = 7

# Whether the background loop itself is running in THIS process. User-facing
# state (alerts/logs/patrol bookkeeping) lives in Postgres, never in RAM: it
# must survive restarts/deploys, and it's what lets the patrol move to its own
# worker process while the API keeps serving reads.
_daemon_active = False


def _new_patrol_buffer() -> dict:
    """Scratch state for ONE patrol of ONE user. The sync patrol code collects
    findings here (it can't await), and the async loop persists the buffer to
    Postgres when the patrol returns."""
    return {
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
# Buffer helpers — operate on one patrol's buffer, never shared state
# ---------------------------------------------------------------------------


def _log(user_state: dict, msg: str, level: str = "info"):
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level, "message": msg}
    user_state["logs"].append(entry)
    getattr(logger, level, logger.info)(msg)


def _alert(user_state: dict, msg: str, severity: str = "warning"):
    user_state["alerts"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": msg,
        "severity": severity,
    })


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


IDLE_CPU_THRESHOLD = 5.0
IDLE_MIN_DATAPOINTS = 3
IDLE_WINDOW_MINUTES = 30


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
                    # Bodyguard only watches ManagedBy=Nimbus resources, which
                    # only exist once the user has deployed something — skip the
                    # AssumeRole + 6 AWS API calls per cycle for users who
                    # connected AWS but never deployed.
                    has_deploy = await db.scalar(
                        select(Deployment.id).where(Deployment.user_id == user.id).limit(1)
                    )
                    if has_deploy is None:
                        continue

                    buffer = _new_patrol_buffer()
                    try:
                        session = await get_user_boto3_session(db, user.id)
                        if session is None:
                            continue
                        # boto3 is synchronous — run the patrol in a thread so it
                        # doesn't block the event loop
                        await asyncio.to_thread(_run_patrol, session, buffer)
                    except Exception as e:
                        _log(buffer, f"Patrol error: {e}", "error")
                    await _persist_patrol(db, user.id, buffer)

                await _prune_old_logs(db)
        except Exception as e:
            logger.error(f"Bodyguard loop error enumerating users: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def _persist_patrol(db, user_id, buffer: dict) -> None:
    """Write one patrol's findings to Postgres. Timestamps come from the buffer
    (when the finding happened), not commit time."""
    for entry in buffer["logs"]:
        db.add(BodyguardLog(
            user_id=user_id,
            level=entry["level"],
            message=entry["message"],
            created_at=datetime.fromisoformat(entry["timestamp"]),
        ))
    for entry in buffer["alerts"]:
        db.add(BodyguardAlert(
            user_id=user_id,
            message=entry["message"],
            severity=entry["severity"],
            created_at=datetime.fromisoformat(entry["timestamp"]),
        ))

    status = await db.get(BodyguardStatus, user_id)
    if status is None:
        status = BodyguardStatus(user_id=user_id, sub_resources={})
        db.add(status)
    status.last_check = datetime.now(timezone.utc)
    status.instances_stopped = (status.instances_stopped or 0) + buffer["instances_stopped"]
    status.sub_resources = buffer["sub_resources"]
    await db.commit()


async def _prune_old_logs(db) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)
    await db.execute(delete(BodyguardLog).where(BodyguardLog.created_at < cutoff))
    await db.commit()


def _run_patrol(session, user_state: dict):
    """One patrol cycle for one user's AWS account. Deliberately deterministic:
    every decision rule here (idle → stop, orphaned → alert) is a simple
    threshold check, and the old LLM-driven patrol burned a Bedrock tool-loop
    per user every CHECK_INTERVAL, 24/7 — real money for decisions plain code
    makes identically. (That was the source of a surprise Bedrock bill: patrols
    always used the env-default provider regardless of the user's chat model.)"""
    instances = _handle_list_running_instances({}, session)["instances"]
    _log(user_state, f"Patrol: {len(instances)} running Nimbus instance(s)")

    non_free = [i for i in instances if not i["is_free_tier"]]
    for inst in non_free:
        _alert(
            user_state,
            f"Non-free-tier instance '{inst['name']}' ({inst['instance_type']}) is running and accruing charges.",
            "warning",
        )
    free = [i for i in instances if i["is_free_tier"]]
    if len(free) > 1:
        _alert(
            user_state,
            f"{len(free)} free-tier instances are running simultaneously — your 750 free hours/month burn {len(free)}x faster.",
            "warning",
        )

    for inst in instances:
        iid = inst["instance_id"]
        try:
            metrics = _handle_get_cpu_metrics({"instance_id": iid, "minutes": IDLE_WINDOW_MINUTES}, session)
        except Exception as e:
            _log(user_state, f"CPU check failed for {iid}: {e}", "error")
            continue
        avg = metrics.get("avg_cpu")
        if avg is None:
            _log(user_state, f"{iid}: no CPU data yet (new instance) — not touching it")
            continue
        if avg < IDLE_CPU_THRESHOLD and metrics.get("datapoints", 0) >= IDLE_MIN_DATAPOINTS:
            reason = (
                f"Average CPU {avg}% over the last {IDLE_WINDOW_MINUTES} minutes "
                f"(threshold {IDLE_CPU_THRESHOLD}%) — instance appears idle."
            )
            # Alert BEFORE stopping, so the user always sees why.
            _alert(user_state, f"Stopping idle instance '{inst['name']}' ({iid}): {reason}", "critical")
            try:
                _handle_stop_instance({"instance_id": iid, "reason": reason}, session, user_state)
            except Exception as e:
                _log(user_state, f"Failed to stop {iid}: {e}", "error")

    try:
        vols = _handle_check_ebs_volumes({}, session, user_state)
        if vols["orphaned_count"]:
            _alert(
                user_state,
                f"{vols['orphaned_count']} orphaned EBS volume(s) costing ~${vols['orphaned_monthly_cost']}/month — attached to nothing.",
                "warning",
            )
    except Exception as e:
        _log(user_state, f"EBS check failed: {e}", "error")

    try:
        eips = _handle_check_elastic_ips({}, session, user_state)
        unassociated = [e_ for e_ in eips["elastic_ips"] if not e_["attached_to"]]
        if unassociated:
            cost = round(sum(e_["cost_per_month"] for e_ in unassociated), 2)
            _alert(
                user_state,
                f"{len(unassociated)} unassociated Elastic IP(s) costing ~${cost}/month while idle.",
                "warning",
            )
    except Exception as e:
        _log(user_state, f"Elastic IP check failed: {e}", "error")

    try:
        _handle_check_snapshots({}, session, user_state)
    except Exception as e:
        _log(user_state, f"Snapshot check failed: {e}", "error")


# Strong reference to the daemon task — asyncio holds tasks weakly, so without
# this the patrol loop could be garbage-collected mid-flight and silently die
# (same bug class as chat.py's _turn_tasks).
_daemon_task: asyncio.Task | None = None


def start_bodyguard():
    global _daemon_active, _daemon_task
    _daemon_active = True
    _daemon_task = asyncio.get_running_loop().create_task(_bodyguard_loop())


async def run_forever():
    """Entry point for the standalone worker process (worker.py): run the patrol
    loop in the foreground until cancelled, instead of as a daemon task inside
    the API process."""
    global _daemon_active
    _daemon_active = True
    try:
        await _bodyguard_loop()
    finally:
        _daemon_active = False


def stop_bodyguard():
    global _daemon_active
    _daemon_active = False
    if _daemon_task is not None:
        _daemon_task.cancel()  # don't leave the loop sleeping through shutdown
    logger.info("Bodyguard agent stopped")


# ---------------------------------------------------------------------------
# Public status API — async DB reads, scoped to one user. Same JSON shapes the
# frontend always consumed; only the storage moved from RAM to Postgres.
# ---------------------------------------------------------------------------


def _alert_json(a: BodyguardAlert) -> dict:
    return {
        "id": str(a.id),
        "timestamp": a.created_at.isoformat() if a.created_at else None,
        "message": a.message,
        "severity": a.severity,
        "read": a.read,
    }


def _log_json(entry: BodyguardLog) -> dict:
    return {
        "timestamp": entry.created_at.isoformat() if entry.created_at else None,
        "level": entry.level,
        "message": entry.message,
    }


async def get_status(db, user_id) -> dict:
    status = await db.get(BodyguardStatus, user_id)
    logs = (await db.scalars(
        select(BodyguardLog).where(BodyguardLog.user_id == user_id)
        .order_by(BodyguardLog.created_at.desc()).limit(20)
    )).all()
    alerts = (await db.scalars(
        select(BodyguardAlert).where(BodyguardAlert.user_id == user_id)
        .order_by(BodyguardAlert.created_at.desc()).limit(20)
    )).all()
    unread = (await db.scalars(
        select(BodyguardAlert)
        .where(BodyguardAlert.user_id == user_id, BodyguardAlert.read.is_(False))
        .order_by(BodyguardAlert.created_at.asc()).limit(100)
    )).all()

    last_check = status.last_check if status else None
    # "running" must stay truthful once the patrol moves to its own worker
    # process: this API process won't host the daemon, so a fresh last_check
    # (written by whoever IS patrolling) also counts as running.
    recently_patrolled = bool(
        last_check
        and datetime.now(timezone.utc) - last_check < timedelta(seconds=2 * CHECK_INTERVAL)
    )
    return {
        "running": _daemon_active or recently_patrolled,
        "last_check": last_check.isoformat() if last_check else None,
        "instances_stopped_total": status.instances_stopped if status else 0,
        "recent_logs": [_log_json(e) for e in reversed(logs)],
        "unread_alerts": [_alert_json(a) for a in unread],
        "all_alerts": [_alert_json(a) for a in reversed(alerts)],
        "sub_resources": (status.sub_resources if status else None)
        or {"volumes": [], "elastic_ips": [], "snapshots": []},
    }


async def get_alerts(db, user_id) -> list:
    rows = (await db.scalars(
        select(BodyguardAlert).where(BodyguardAlert.user_id == user_id)
        .order_by(BodyguardAlert.created_at.desc()).limit(100)
    )).all()
    return [_alert_json(a) for a in reversed(rows)]


async def mark_alert_read(db, user_id, alert_id: str) -> None:
    try:
        aid = uuid.UUID(alert_id)
    except (ValueError, AttributeError, TypeError):
        return  # pre-migration "alert-<ms>" ids or garbage — nothing to mark
    alert = (await db.scalars(
        select(BodyguardAlert).where(BodyguardAlert.id == aid, BodyguardAlert.user_id == user_id)
    )).first()
    if alert is not None:
        alert.read = True
        await db.commit()
