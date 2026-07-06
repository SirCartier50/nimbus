"""Cloud Control provider — the boto3 `cloudcontrol` client is mocked, so no real
AWS calls happen and the async poll loop's sleep is patched out."""
import json
from unittest.mock import MagicMock, patch

import pytest

from providers import cloud_control


def _progress(status, identifier=None, token="tok", msg=None):
    p = {"OperationStatus": status, "RequestToken": token}
    if identifier is not None:
        p["Identifier"] = identifier
    if msg is not None:
        p["StatusMessage"] = msg
    return {"ProgressEvent": p}


def _patch_client(client):
    return patch.object(cloud_control, "_client", return_value=client)


def test_create_resource_success_and_injects_tags():
    client = MagicMock()
    client.create_resource.return_value = _progress("SUCCESS", identifier="my-bucket")
    with _patch_client(client):
        result = cloud_control.create_resource(
            "AWS::S3::Bucket", {"BucketName": "my-bucket"}, tags={"ManagedBy": "Nimbus"}
        )
    assert result["success"] and result["resource_id"] == "my-bucket"
    kwargs = client.create_resource.call_args.kwargs
    assert kwargs["TypeName"] == "AWS::S3::Bucket"
    sent = json.loads(kwargs["DesiredState"])
    assert {"Key": "ManagedBy", "Value": "Nimbus"} in sent["Tags"]


def test_create_resource_polls_until_terminal():
    client = MagicMock()
    client.create_resource.return_value = _progress("IN_PROGRESS")
    client.get_resource_request_status.side_effect = [
        _progress("IN_PROGRESS"),
        _progress("SUCCESS", identifier="i-1"),
    ]
    with _patch_client(client), patch.object(cloud_control.time, "sleep"):
        result = cloud_control.create_resource("AWS::EC2::Instance", {}, poll_interval=0)
    assert result["success"] and result["resource_id"] == "i-1"
    assert client.get_resource_request_status.call_count == 2


def test_create_resource_failure_reports_error():
    client = MagicMock()
    client.create_resource.return_value = _progress("FAILED", msg="resource limit exceeded")
    with _patch_client(client):
        result = cloud_control.create_resource("AWS::S3::Bucket", {"BucketName": "x"})
    assert result["success"] is False
    assert "limit exceeded" in result["error"]


def test_create_resource_retries_without_tags_on_tag_error():
    client = MagicMock()
    client.create_resource.side_effect = [
        Exception("Property Tags is not supported for this resource type"),
        _progress("SUCCESS", identifier="r1"),
    ]
    with _patch_client(client):
        result = cloud_control.create_resource("AWS::Foo::Bar", {"Name": "x"}, tags={"ManagedBy": "Nimbus"})
    assert result["success"] and result["resource_id"] == "r1"
    assert client.create_resource.call_count == 2
    second = json.loads(client.create_resource.call_args.kwargs["DesiredState"])
    assert "Tags" not in second   # the retry dropped the tags


def test_create_resource_reraises_non_tag_error():
    client = MagicMock()
    client.create_resource.side_effect = Exception("AccessDenied")
    with _patch_client(client), pytest.raises(Exception, match="AccessDenied"):
        cloud_control.create_resource("AWS::S3::Bucket", {}, tags={"ManagedBy": "Nimbus"})
    assert client.create_resource.call_count == 1   # not retried


def test_get_resource_parses_properties_json():
    client = MagicMock()
    client.get_resource.return_value = {
        "ResourceDescription": {"Identifier": "my-bucket", "Properties": json.dumps({"BucketName": "my-bucket"})}
    }
    with _patch_client(client):
        result = cloud_control.get_resource("AWS::S3::Bucket", "my-bucket")
    assert result["resource_id"] == "my-bucket"
    assert result["properties"] == {"BucketName": "my-bucket"}


def test_list_resources_paginates_across_next_tokens():
    client = MagicMock()
    client.list_resources.side_effect = [
        {"ResourceDescriptions": [{"Identifier": "a", "Properties": json.dumps({"x": 1})}], "NextToken": "n"},
        {"ResourceDescriptions": [{"Identifier": "b", "Properties": json.dumps({"x": 2})}]},
    ]
    with _patch_client(client):
        result = cloud_control.list_resources("AWS::S3::Bucket")
    assert [r["resource_id"] for r in result["resources"]] == ["a", "b"]
    assert client.list_resources.call_count == 2


def test_delete_resource_success():
    client = MagicMock()
    client.delete_resource.return_value = _progress("SUCCESS", identifier="my-bucket")
    with _patch_client(client):
        result = cloud_control.delete_resource("AWS::S3::Bucket", "my-bucket")
    assert result["success"]
    assert client.delete_resource.call_args.kwargs == {"TypeName": "AWS::S3::Bucket", "Identifier": "my-bucket"}


def test_with_tags_overrides_caller_tag_of_same_key():
    state = cloud_control._with_tags(
        {"Tags": [{"Key": "ManagedBy", "Value": "someone-else"}, {"Key": "env", "Value": "prod"}]},
        {"ManagedBy": "Nimbus"},
    )
    tags = {t["Key"]: t["Value"] for t in state["Tags"]}
    assert tags == {"env": "prod", "ManagedBy": "Nimbus"}
