from fastapi import APIRouter
from pydantic import BaseModel

from agents.bodyguard import get_alerts, get_status as bodyguard_status, mark_alert_read
from utils.aws_clients import (
    get_dynamodb_client,
    get_ec2_client,
    get_lambda_client,
    get_s3_client,
)

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard():
    return {
        "ec2": _ec2_resources(),
        "s3": _s3_resources(),
        "dynamodb": _dynamodb_resources(),
        "lambda": _lambda_resources(),
        "bodyguard": bodyguard_status(),
    }


def _ec2_resources() -> list:
    try:
        ec2 = get_ec2_client()
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


def _s3_resources() -> list:
    try:
        s3 = get_s3_client()
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


def _dynamodb_resources() -> list:
    try:
        dynamo = get_dynamodb_client()
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


def _lambda_resources() -> list:
    try:
        lc = get_lambda_client()
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


@router.get("/dashboard/alerts")
async def dashboard_alerts():
    return {"alerts": get_alerts()}


class AlertReadBody(BaseModel):
    alert_id: str


@router.post("/dashboard/alerts/read")
async def read_alert(body: AlertReadBody):
    mark_alert_read(body.alert_id)
    return {"ok": True}


@router.get("/dashboard/bodyguard")
async def bodyguard_state():
    return bodyguard_status()
