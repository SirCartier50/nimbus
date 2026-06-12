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


@router.get("/dashboard/cost-details/{resource_type}/{resource_id}")
async def get_cost_details(resource_type: str, resource_id: str):
    """Return detailed cost breakdown for a specific resource, including sub-resources."""
    details = {"resource_id": resource_id, "resource_type": resource_type, "costs": [], "total_monthly": 0.0}

    if resource_type == "ec2":
        ec2 = get_ec2_client()
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
