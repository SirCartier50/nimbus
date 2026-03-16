import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from utils.aws_clients import get_cloudwatch_client, get_ec2_client

logger = logging.getLogger("bodyguard")

CPU_THRESHOLD = 5.0
IDLE_WINDOW_MINUTES = 30
MIN_DATAPOINTS = 3
CHECK_INTERVAL = 300

state = {
    "running": False,
    "last_check": None,
    "instances_stopped": 0,
    "logs": [],
    "alerts": [],
}


def _log(msg: str, level: str = "info"):
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level, "message": msg}
    state["logs"].append(entry)
    if len(state["logs"]) > 200:
        state["logs"] = state["logs"][-100:]
    getattr(logger, level, logger.info)(msg)


def _alert(msg: str, severity: str = "warning"):
    state["alerts"].append(
        {
            "id": f"alert-{int(time.time() * 1000)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": msg,
            "severity": severity,
            "read": False,
        }
    )
    if len(state["alerts"]) > 100:
        state["alerts"] = state["alerts"][-50:]


def _check_idle_instances():
    ec2 = get_ec2_client()
    cw = get_cloudwatch_client()

    try:
        resp = ec2.describe_instances(
            Filters=[
                {"Name": "tag:ManagedBy", "Values": ["Nimbus"]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )
        instances = [
            inst
            for r in resp.get("Reservations", [])
            for inst in r.get("Instances", [])
        ]

        if not instances:
            _log("No running Nimbus instances found")
            return

        _log(f"Patrolling {len(instances)} running instance(s)")

        for inst in instances:
            iid = inst["InstanceId"]
            name = next(
                (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                iid,
            )

            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=IDLE_WINDOW_MINUTES)

            metrics = cw.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": iid}],
                StartTime=start,
                EndTime=end,
                Period=300,
                Statistics=["Average"],
            )
            points = metrics.get("Datapoints", [])

            if not points:
                _log(f"{name} ({iid}): no CPU data yet (instance may be new)")
                continue

            avg_cpu = sum(p["Average"] for p in points) / len(points)
            _log(f"{name} ({iid}): avg CPU {avg_cpu:.2f}% over last {len(points)} periods")

            if avg_cpu < CPU_THRESHOLD and len(points) >= MIN_DATAPOINTS:
                _log(f"Stopping idle instance {name} ({iid}) — CPU {avg_cpu:.2f}%", "warning")
                ec2.stop_instances(InstanceIds=[iid])
                state["instances_stopped"] += 1
                _alert(
                    f"Auto-stopped idle instance '{name}' ({iid}). "
                    f"Average CPU was {avg_cpu:.2f}% — protecting your free-tier hours!",
                    "info",
                )

    except Exception as e:
        _log(f"Error in idle check: {e}", "error")


def _check_free_tier_hours():
    ec2 = get_ec2_client()
    try:
        resp = ec2.describe_instances(
            Filters=[
                {"Name": "instance-type", "Values": ["t2.micro", "t3.micro"]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )
        running = sum(
            1
            for r in resp.get("Reservations", [])
            for i in r.get("Instances", [])
            if i["State"]["Name"] == "running"
        )

        if running > 1:
            _alert(
                f"{running} t2/t3.micro instances are running simultaneously. "
                "Free tier covers 750 hours/month total — running multiple instances burns through it faster.",
                "warning",
            )
            _log(f"Free-tier alert: {running} instances running concurrently", "warning")

    except Exception as e:
        _log(f"Error in free-tier check: {e}", "error")


async def _bodyguard_loop():
    _log("Bodyguard agent started")
    state["running"] = True

    while state["running"]:
        try:
            state["last_check"] = datetime.now(timezone.utc).isoformat()
            _check_idle_instances()
            _check_free_tier_hours()
            _log(f"Patrol complete. Next check in {CHECK_INTERVAL}s")
        except Exception as e:
            _log(f"Unhandled error in bodyguard loop: {e}", "error")

        await asyncio.sleep(CHECK_INTERVAL)


def start_bodyguard():
    loop = asyncio.get_event_loop()
    loop.create_task(_bodyguard_loop())


def stop_bodyguard():
    state["running"] = False
    _log("Bodyguard agent stopped")


def get_status() -> dict:
    return {
        "running": state["running"],
        "last_check": state["last_check"],
        "instances_stopped_total": state["instances_stopped"],
        "recent_logs": state["logs"][-20:],
        "unread_alerts": [a for a in state["alerts"] if not a["read"]],
        "all_alerts": state["alerts"][-20:],
    }


def get_alerts() -> list:
    return state["alerts"]


def mark_alert_read(alert_id: str):
    for a in state["alerts"]:
        if a["id"] == alert_id:
            a["read"] = True
            break
