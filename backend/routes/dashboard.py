import asyncio
import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agents.bodyguard import get_alerts, get_status as bodyguard_status, mark_alert_read
from db.crud import get_or_create_user
from db.deps import get_db
from utils.aws_clients import (
    get_dynamodb_client,
    get_ec2_client,
    get_lambda_client,
    get_s3_client,
)
from utils.redis_client import get_async_redis
from utils.user_aws import get_user_boto3_session

logger = logging.getLogger("dashboard")

router = APIRouter()

# Measured live: the four resource-type lookups below are real, sequential AWS API
# calls (S3's per-bucket get_bucket_tagging and DynamoDB's per-table describe+
# list_tags are the worst offenders) — 3.7s end-to-end before this change. Two
# fixes:
#   1. Run all four concurrently instead of sequentially (asyncio.gather +
#      to_thread, since boto3 is synchronous) — cuts latency to the slowest single
#      resource type instead of the sum of all four.
#   2. Cache the combined result briefly per user, so the frontend's 8s poll
#      interval doesn't pay the full AWS round-trip on every single tick.
#      The cache lives in Redis when REDIS_URL is set (shared across workers,
#      TTL-evicted by Redis itself); otherwise in this dict, with stale entries
#      overwritten in place per user.
_DASHBOARD_CACHE_TTL_SECONDS = 8
_dashboard_cache: dict[uuid.UUID, tuple[dict, float]] = {}


def clear_dashboard_cache() -> None:
    """Test hook — drop all cached dashboard snapshots."""
    _dashboard_cache.clear()


async def _cache_get(user_id: uuid.UUID) -> dict | None:
    redis = get_async_redis()
    if redis is not None:
        try:
            raw = await redis.get(f"nimbus:dash:{user_id}")
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning("Redis dashboard-cache read failed (%s) — using in-process cache", e)
    cached = _dashboard_cache.get(user_id)
    if cached and cached[1] > time.time():
        return cached[0]
    return None


async def _cache_put(user_id: uuid.UUID, payload: dict) -> None:
    redis = get_async_redis()
    if redis is not None:
        try:
            await redis.set(f"nimbus:dash:{user_id}", json.dumps(payload), ex=_DASHBOARD_CACHE_TTL_SECONDS)
            return
        except Exception as e:
            logger.warning("Redis dashboard-cache write failed (%s) — using in-process cache", e)
    _dashboard_cache[user_id] = (payload, time.time() + _DASHBOARD_CACHE_TTL_SECONDS)


@router.get("/dashboard")
async def get_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)

    cached = await _cache_get(user.id)
    if cached is not None:
        return cached

    aws_session = await get_user_boto3_session(db, user.id)
    ec2, s3, dynamodb, lambda_ = await asyncio.gather(
        asyncio.to_thread(_ec2_resources, aws_session),
        asyncio.to_thread(_s3_resources, aws_session),
        asyncio.to_thread(_dynamodb_resources, aws_session),
        asyncio.to_thread(_lambda_resources, aws_session),
    )
    payload = {
        "ec2": ec2,
        "s3": s3,
        "dynamodb": dynamodb,
        "lambda": lambda_,
        "bodyguard": await bodyguard_status(db, user.id),
    }
    await _cache_put(user.id, payload)
    return payload


def _ec2_resources(session=None) -> list:
    try:
        ec2 = get_ec2_client(session)
        resp = ec2.describe_instances(
            Filters=[{"Name": "tag:ManagedBy", "Values": ["Nimbus"]}]
        )
        result = []
        for reservation in resp.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                state = inst["State"]["Name"]
                if state == "terminated":
                    continue
                name = next(
                    (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                    inst["InstanceId"],
                )
                result.append(
                    {
                        "id": inst["InstanceId"],
                        "name": name,
                        "type": inst.get("InstanceType"),
                        "state": state,
                        "public_ip": inst.get("PublicIpAddress"),
                        "launch_time": (
                            inst["LaunchTime"].isoformat()
                            if inst.get("LaunchTime")
                            else None
                        ),
                        "resource_type": "ec2",
                    }
                )
        return result
    except Exception as e:
        return [{"error": str(e), "resource_type": "ec2"}]


def _s3_resources(session=None) -> list:
    try:
        s3 = get_s3_client(session)
        resp = s3.list_buckets()
        result = []
        for bucket in resp.get("Buckets", []):
            bname = bucket["Name"]
            try:
                tags = s3.get_bucket_tagging(Bucket=bname)
                tag_map = {t["Key"]: t["Value"] for t in tags.get("TagSet", [])}
                if tag_map.get("ManagedBy") != "Nimbus":
                    continue
            except Exception:
                continue
            result.append(
                {
                    "id": bname,
                    "name": bname,
                    "created": (
                        bucket["CreationDate"].isoformat()
                        if bucket.get("CreationDate")
                        else None
                    ),
                    "state": "active",
                    "resource_type": "s3",
                }
            )
        return result
    except Exception as e:
        return [{"error": str(e), "resource_type": "s3"}]


def _dynamodb_resources(session=None) -> list:
    try:
        dynamo = get_dynamodb_client(session)
        tables = dynamo.list_tables().get("TableNames", [])
        result = []
        for tname in tables:
            try:
                desc = dynamo.describe_table(TableName=tname)["Table"]
                tags_resp = dynamo.list_tags_of_resource(ResourceArn=desc["TableArn"])
                tag_map = {t["Key"]: t["Value"] for t in tags_resp.get("Tags", [])}
                if tag_map.get("ManagedBy") != "Nimbus":
                    continue
                result.append(
                    {
                        "id": tname,
                        "name": tname,
                        "state": desc.get("TableStatus", "UNKNOWN").lower(),
                        "item_count": desc.get("ItemCount", 0),
                        "size_bytes": desc.get("TableSizeBytes", 0),
                        "resource_type": "dynamodb",
                    }
                )
            except Exception:
                continue
        return result
    except Exception as e:
        return [{"error": str(e), "resource_type": "dynamodb"}]


def _lambda_resources(session=None) -> list:
    try:
        lc = get_lambda_client(session)
        fns = lc.list_functions().get("Functions", [])
        result = []
        for fn in fns:
            try:
                tags = lc.list_tags(Resource=fn["FunctionArn"]).get("Tags", {})
            except Exception:
                tags = fn.get("Tags", {})
            if tags.get("ManagedBy") != "Nimbus":
                continue
            result.append(
                {
                    "id": fn["FunctionName"],
                    "name": fn["FunctionName"],
                    "runtime": fn.get("Runtime"),
                    "state": "active",
                    "last_modified": fn.get("LastModified"),
                    "memory": fn.get("MemorySize"),
                    "resource_type": "lambda",
                }
            )
        return result
    except Exception as e:
        return [{"error": str(e), "resource_type": "lambda"}]


@router.get("/dashboard/cost-details/{resource_type}/{resource_id}")
async def get_cost_details(
    resource_type: str,
    resource_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return detailed cost breakdown for a specific resource, including sub-resources."""
    user = await get_or_create_user(db, request.state.user_id)
    aws_session = await get_user_boto3_session(db, user.id)
    details = {"resource_id": resource_id, "resource_type": resource_type, "costs": [], "total_monthly": 0.0}

    if resource_type == "ec2":
        ec2 = get_ec2_client(aws_session)
        try:
            # Instance itself
            resp = ec2.describe_instances(InstanceIds=[resource_id])
            inst = resp["Reservations"][0]["Instances"][0]
            inst_state = inst["State"]["Name"]
            inst_type = inst.get("InstanceType", "t2.micro")

            # EC2 compute cost
            if inst_state == "running":
                is_free_tier = inst_type in ("t2.micro", "t3.micro")
                details["costs"].append({
                    "item": f"EC2 Compute ({inst_type})",
                    "monthly": 0.0 if is_free_tier else 8.50,
                    "note": "Free tier: 750 hrs/month for 12 months" if is_free_tier else f"~$0.0116/hr for {inst_type}",
                })
            else:
                details["costs"].append({
                    "item": f"EC2 Compute ({inst_type})",
                    "monthly": 0.0,
                    "note": f"Instance is {inst_state} — no compute charges",
                })

            # Public IPv4 cost (charged even on free tier since Feb 2024)
            public_ip = inst.get("PublicIpAddress")
            if public_ip and inst_state == "running":
                details["costs"].append({
                    "item": f"Public IPv4 ({public_ip})",
                    "monthly": round(0.005 * 730, 2),
                    "note": "AWS charges $0.005/hr for all public IPv4 addresses",
                })

            # EBS volumes attached to this instance
            block_devices = inst.get("BlockDeviceMappings", [])
            for bd in block_devices:
                vol_id = bd.get("Ebs", {}).get("VolumeId")
                if not vol_id:
                    continue
                try:
                    vol_resp = ec2.describe_volumes(VolumeIds=[vol_id])
                    vol = vol_resp["Volumes"][0]
                    size_gb = vol.get("Size", 0)
                    vol_type = vol.get("VolumeType", "gp2")
                    cost_per_gb = 0.08 if vol_type == "gp3" else 0.10
                    monthly = round(size_gb * cost_per_gb, 2)
                    free_note = ""
                    if size_gb <= 30:
                        free_note = " (free tier: 30 GB/month for 12 months)"
                        monthly = 0.0
                    details["costs"].append({
                        "item": f"EBS Volume ({vol_id}, {size_gb} GB {vol_type})",
                        "monthly": monthly,
                        "note": f"${cost_per_gb}/GB/month{free_note}",
                    })
                except Exception:
                    pass

            # Security groups (free)
            for sg in inst.get("SecurityGroups", []):
                details["costs"].append({
                    "item": f"Security Group ({sg.get('GroupName', sg.get('GroupId'))})",
                    "monthly": 0.0,
                    "note": "No charge for security groups",
                })

            # Network interface
            for ni in inst.get("NetworkInterfaces", []):
                details["costs"].append({
                    "item": f"Network Interface ({ni.get('NetworkInterfaceId', 'N/A')})",
                    "monthly": 0.0,
                    "note": "No charge for default ENIs",
                })

        except Exception as e:
            details["costs"].append({"item": "Error", "monthly": 0.0, "note": str(e)})

    elif resource_type == "s3":
        details["costs"].append({
            "item": f"S3 Bucket ({resource_id})",
            "monthly": 0.0,
            "note": "Free tier: 5 GB storage, 20k GET, 2k PUT/month for 12 months",
        })
        details["costs"].append({
            "item": "S3 Data Transfer",
            "monthly": 0.0,
            "note": "Free tier: 100 GB out/month for 12 months",
        })

    elif resource_type == "dynamodb":
        details["costs"].append({
            "item": f"DynamoDB Table ({resource_id})",
            "monthly": 0.0,
            "note": "Always free: 25 GB storage, 25 WCU/RCU with on-demand",
        })

    elif resource_type == "lambda":
        details["costs"].append({
            "item": f"Lambda Function ({resource_id})",
            "monthly": 0.0,
            "note": "Always free: 1M requests/month, 400k GB-seconds",
        })

    details["total_monthly"] = round(sum(c["monthly"] for c in details["costs"]), 2)
    return details


@router.get("/dashboard/alerts")
async def dashboard_alerts(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    return {"alerts": await get_alerts(db, user.id)}


class AlertReadBody(BaseModel):
    alert_id: str


@router.post("/dashboard/alerts/read")
async def read_alert(body: AlertReadBody, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    await mark_alert_read(db, user.id, body.alert_id)
    return {"ok": True}


@router.get("/dashboard/bodyguard")
async def bodyguard_state(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    return await bodyguard_status(db, user.id)
