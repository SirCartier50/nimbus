"""Generic AWS provisioning via the Cloud Control API (`cloudcontrol`).

One uniform CRUD interface over ~any CloudFormation-registered resource type, so we can
create/read/delete a resource by its CloudFormation TypeName (e.g. "AWS::S3::Bucket")
plus a JSON desired-state — instead of a hand-written per-service handler. This is the
generic breadth path that complements the curated per-service registry in executor.py;
it does NOT replace the special *actions* Cloud Control's CRUD model can't express
(stop/start an instance, empty-then-delete an S3 bucket).

Cloud Control create/delete are asynchronous: the call returns a ProgressEvent carrying
a RequestToken; we poll `get_resource_request_status` until a terminal state.

Reached through the same in-process, per-user boto3 session as everything else — no
subprocess, no MCP bridge. "Our touch" that stays here: uniform `ManagedBy=Nimbus`
tagging (so Bodyguard still sees these resources). Deep config validation and free-tier
enforcement on this path are intentionally deferred until the Architect emits CFN
TypeNames (that's the LLM-integration step, not built yet).
"""
import json
import time

from utils.aws_clients import get_boto3_session

# Cloud Control OperationStatus values that mean the request is done.
_TERMINAL = {"SUCCESS", "FAILED", "CANCEL_COMPLETE"}
_POLL_INTERVAL = 2.0
_POLL_TIMEOUT = 300.0


def _client(session=None):
    return (session or get_boto3_session()).client("cloudcontrol")


def _wait(client, token: str, poll_interval: float, timeout: float = _POLL_TIMEOUT):
    """Poll a request to a terminal state; return the final ProgressEvent (or the last
    one seen if it never terminates within `timeout`)."""
    deadline = time.monotonic() + timeout
    while True:
        progress = client.get_resource_request_status(RequestToken=token)["ProgressEvent"]
        if progress["OperationStatus"] in _TERMINAL or time.monotonic() >= deadline:
            return progress
        time.sleep(poll_interval)


def _result(client, type_name: str, progress: dict, poll_interval: float) -> dict:
    if progress["OperationStatus"] not in _TERMINAL:
        progress = _wait(client, progress["RequestToken"], poll_interval)
    ok = progress["OperationStatus"] == "SUCCESS"
    return {
        "success": ok,
        "resource_type": type_name,
        "resource_id": progress.get("Identifier"),
        "status": progress["OperationStatus"],
        "error": None if ok else progress.get("StatusMessage") or progress.get("ErrorCode"),
    }


def _with_tags(desired_state: dict, tags: dict) -> dict:
    """Merge tags into the desired-state using CloudFormation's uniform [{Key,Value}]
    shape — our tags win over any the caller already set for the same key."""
    state = dict(desired_state)
    existing = [t for t in state.get("Tags", []) if t.get("Key") not in tags]
    state["Tags"] = existing + [{"Key": k, "Value": v} for k, v in tags.items()]
    return state


def _is_tag_error(err: Exception) -> bool:
    return "tag" in str(err).lower()


def create_resource(type_name: str, desired_state: dict, tags: dict = None,
                    session=None, poll_interval: float = _POLL_INTERVAL) -> dict:
    """Create a resource by CFN TypeName + desired-state dict. Tags are injected
    uniformly; if the resource type doesn't support Tags (a per-type quirk we don't
    want to hardcode), we retry once without them rather than fail the create."""
    client = _client(session)
    state = _with_tags(desired_state, tags) if tags else dict(desired_state)
    try:
        progress = client.create_resource(TypeName=type_name, DesiredState=json.dumps(state))["ProgressEvent"]
    except Exception as e:
        if tags and _is_tag_error(e):
            progress = client.create_resource(
                TypeName=type_name, DesiredState=json.dumps(desired_state)
            )["ProgressEvent"]
        else:
            raise
    return _result(client, type_name, progress, poll_interval)


def delete_resource(type_name: str, identifier: str, session=None,
                    poll_interval: float = _POLL_INTERVAL) -> dict:
    client = _client(session)
    progress = client.delete_resource(TypeName=type_name, Identifier=identifier)["ProgressEvent"]
    return _result(client, type_name, progress, poll_interval)


def get_resource(type_name: str, identifier: str, session=None) -> dict:
    desc = _client(session).get_resource(TypeName=type_name, Identifier=identifier)["ResourceDescription"]
    return {
        "resource_type": type_name,
        "resource_id": desc.get("Identifier"),
        "properties": json.loads(desc["Properties"]) if desc.get("Properties") else {},
    }


def list_resources(type_name: str, session=None) -> dict:
    client = _client(session)
    resources = []
    next_token = None
    while True:
        kwargs = {"TypeName": type_name}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = client.list_resources(**kwargs)
        for d in resp.get("ResourceDescriptions", []):
            resources.append({
                "resource_id": d.get("Identifier"),
                "properties": json.loads(d["Properties"]) if d.get("Properties") else {},
            })
        next_token = resp.get("NextToken")
        if not next_token:
            break
    return {"resource_type": type_name, "resources": resources}
