import json
from unittest.mock import MagicMock, patch

import jsonschema
import pytest

from agents import executor

# ---------------------------------------------------------------------------
# Each test patches executor.client_for to hand back a MagicMock scoped to
# the resource_type under test, so no real boto3/AWS calls ever happen.
# ---------------------------------------------------------------------------


def _patched_client_for(mocks):
    def fake(resource_type, session=None):
        return mocks[resource_type]
    return patch.object(executor, "client_for", side_effect=fake)


def test_create_ec2_instance_applies_free_tier_and_ami_fallback():
    ec2_mock = MagicMock()
    ec2_mock.meta.region_name = "us-east-1"
    ec2_mock.describe_images.return_value = {"Images": [{"ImageId": "ami-999", "CreationDate": "2024-01-01"}]}
    ec2_mock.run_instances.return_value = {"Instances": [{"InstanceId": "i-abc123"}]}

    with _patched_client_for({"ec2_instance": ec2_mock}):
        result = executor._handle_create("ec2_instance", {}, session=None, free_tier_mode=True)

    assert result["success"] and result["resource_id"] == "i-abc123"
    call_kwargs = ec2_mock.run_instances.call_args.kwargs
    assert call_kwargs["ImageId"] == "ami-999"
    assert call_kwargs["InstanceType"] == "t2.micro"
    assert call_kwargs["TagSpecifications"] == [
        {"ResourceType": "instance", "Tags": [{"Key": "ManagedBy", "Value": "Nimbus"}]}
    ]


def test_create_ec2_instance_clamps_non_free_tier_type_when_free_tier_mode_on():
    ec2_mock = MagicMock()
    ec2_mock.meta.region_name = "us-east-1"
    ec2_mock.run_instances.return_value = {"Instances": [{"InstanceId": "i-1"}]}

    with _patched_client_for({"ec2_instance": ec2_mock}):
        executor._handle_create("ec2_instance", {"InstanceType": "m5.xlarge", "ImageId": "ami-x"}, free_tier_mode=True)

    assert ec2_mock.run_instances.call_args.kwargs["InstanceType"] == "t2.micro"


def test_create_s3_bucket_adds_region_config_and_tags_post_create():
    s3_mock = MagicMock()
    s3_mock.meta.region_name = "us-west-2"
    s3_mock.create_bucket.return_value = {"Location": "/my-bucket", "BucketArn": "arn:aws:s3:::my-bucket"}

    with _patched_client_for({"s3_bucket": s3_mock}):
        result = executor._handle_create("s3_bucket", {"Bucket": "my-bucket"})

    assert result["resource_id"] == "my-bucket"
    assert s3_mock.create_bucket.call_args.kwargs["CreateBucketConfiguration"] == {"LocationConstraint": "us-west-2"}
    assert s3_mock.put_bucket_tagging.call_args.kwargs == {
        "Bucket": "my-bucket",
        "Tagging": {"TagSet": [{"Key": "ManagedBy", "Value": "Nimbus"}]},
    }


def test_create_s3_bucket_in_us_east_1_omits_location_constraint():
    """us-east-1 is the one region where CreateBucketConfiguration must NOT
    be set — including it for that region is itself an API error."""
    s3_mock = MagicMock()
    s3_mock.meta.region_name = "us-east-1"
    s3_mock.create_bucket.return_value = {}

    with _patched_client_for({"s3_bucket": s3_mock}):
        executor._handle_create("s3_bucket", {"Bucket": "my-bucket"})

    assert "CreateBucketConfiguration" not in s3_mock.create_bucket.call_args.kwargs


def test_create_lambda_function_fills_role_and_code_when_missing():
    lambda_mock = MagicMock()
    lambda_mock.create_function.return_value = {"FunctionName": "my-fn", "FunctionArn": "arn:aws:lambda:::function:my-fn"}

    with _patched_client_for({"lambda_function": lambda_mock}), \
         patch.object(executor, "_ensure_lambda_role", return_value="arn:aws:iam::123:role/nimbus-lambda-role"):
        result = executor._handle_create("lambda_function", {"FunctionName": "my-fn"})

    assert result["resource_id"] == "my-fn"
    call_kwargs = lambda_mock.create_function.call_args.kwargs
    assert call_kwargs["Role"] == "arn:aws:iam::123:role/nimbus-lambda-role"
    assert call_kwargs["Tags"] == {"ManagedBy": "Nimbus"}
    assert isinstance(call_kwargs["Code"]["ZipFile"], bytes)


def test_create_rejects_missing_required_field_before_calling_aws():
    ddb_mock = MagicMock()
    with _patched_client_for({"dynamodb_table": ddb_mock}):
        with pytest.raises(jsonschema.ValidationError):
            executor._handle_create("dynamodb_table", {"BillingMode": "PAY_PER_REQUEST"})
    ddb_mock.create_table.assert_not_called()


def test_create_iam_role_rejects_missing_trust_policy():
    iam_mock = MagicMock()
    with _patched_client_for({"iam_role": iam_mock}):
        with pytest.raises(jsonschema.ValidationError):
            executor._handle_create("iam_role", {"RoleName": "x"})
    iam_mock.create_role.assert_not_called()


def test_create_cloudfront_tags_using_arn_not_id():
    cf_mock = MagicMock()
    cf_mock.create_distribution.return_value = {
        "Distribution": {"Id": "DIST123", "ARN": "arn:aws:cloudfront::123:distribution/DIST123"},
        "ETag": "E123",
    }
    config = {
        "DistributionConfig": {
            "CallerReference": "ref1",
            "Comment": "test",
            "Enabled": False,
            "DefaultCacheBehavior": {"TargetOriginId": "origin1", "ViewerProtocolPolicy": "allow-all"},
            "Origins": {"Quantity": 0, "Items": []},
        }
    }

    with _patched_client_for({"cloudfront": cf_mock}):
        result = executor._handle_create("cloudfront", config)

    assert result["resource_id"] == "DIST123"
    assert cf_mock.tag_resource.call_args.kwargs["Resource"] == "arn:aws:cloudfront::123:distribution/DIST123"


def test_create_ecs_cluster_uses_lowercase_tags():
    ecs_mock = MagicMock()
    ecs_mock.create_cluster.return_value = {
        "cluster": {"clusterArn": "arn:aws:ecs:::cluster/my-cluster", "clusterName": "my-cluster"}
    }

    with _patched_client_for({"ecs_cluster": ecs_mock}):
        result = executor._handle_create("ecs_cluster", {"clusterName": "my-cluster"})

    assert result["resource_id"] == "arn:aws:ecs:::cluster/my-cluster"
    assert ecs_mock.create_cluster.call_args.kwargs["tags"] == [{"key": "ManagedBy", "value": "Nimbus"}]


def test_delete_vpc_uses_singular_id_param():
    vpc_mock = MagicMock()
    with _patched_client_for({"vpc": vpc_mock}):
        executor._handle_delete("vpc", {"resource_id": "vpc-1"})
    assert vpc_mock.delete_vpc.call_args.kwargs == {"VpcId": "vpc-1"}


def test_delete_s3_bucket_empties_before_deleting():
    s3_mock = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": [{"Key": "a.txt"}, {"Key": "b.txt"}]}]
    s3_mock.get_paginator.return_value = paginator

    with _patched_client_for({"s3_bucket": s3_mock}):
        executor._handle_delete("s3_bucket", {"resource_id": "my-bucket"})

    s3_mock.delete_objects.assert_called_once_with(
        Bucket="my-bucket", Delete={"Objects": [{"Key": "a.txt"}, {"Key": "b.txt"}]}
    )
    s3_mock.delete_bucket.assert_called_once_with(Bucket="my-bucket")


def test_delete_cloudfront_fetches_etag_first():
    cf_mock = MagicMock()
    cf_mock.get_distribution.return_value = {"ETag": "E456", "Distribution": {"Id": "DIST1"}}

    with _patched_client_for({"cloudfront": cf_mock}):
        executor._handle_delete("cloudfront", {"resource_id": "DIST1"})

    assert cf_mock.delete_distribution.call_args.kwargs == {"Id": "DIST1", "IfMatch": "E456"}


def test_create_and_generic_tools_have_matching_handler_names():
    """run_executor wires one handler per tool name it advertises to Bedrock —
    a mismatch here would mean the model could request a tool with no handler."""
    handlers = {f"create_{rt}": None for rt in executor.registry.REGISTRY}
    handlers.update({"get_resource_status": None, "list_resources": None, "stop_ec2_instance": None, "delete_resource": None})

    tools = list(executor.CREATE_TOOLS) + list(executor.GENERIC_TOOLS) + [executor.STOP_EC2_TOOL, executor.DELETE_TOOL]
    tool_names = {t["toolSpec"]["name"] for t in tools}

    assert tool_names == set(handlers.keys())


# ---------------------------------------------------------------------------
# Cloud Control (generic) path — boto3 cloudcontrol client mocked, no LLM.
# ---------------------------------------------------------------------------


def _cc_progress(status="SUCCESS", identifier="r1"):
    return {"ProgressEvent": {"OperationStatus": status, "Identifier": identifier, "RequestToken": "t"}}


def test_cc_create_handler_injects_nimbus_tag():
    client = MagicMock()
    client.create_resource.return_value = _cc_progress(identifier="my-queue")
    with patch("providers.cloud_control._client", return_value=client):
        result = executor._handle_cc_create({"type_name": "AWS::SQS::Queue", "config": {"QueueName": "my-queue"}})
    assert result["success"] and result["resource_id"] == "my-queue"
    sent = json.loads(client.create_resource.call_args.kwargs["DesiredState"])
    assert {"Key": "ManagedBy", "Value": "Nimbus"} in sent["Tags"]


def test_cc_delete_handler_calls_cloud_control():
    client = MagicMock()
    client.delete_resource.return_value = _cc_progress(identifier="my-queue")
    with patch("providers.cloud_control._client", return_value=client):
        result = executor._handle_cc_delete({"type_name": "AWS::SQS::Queue", "resource_id": "my-queue"})
    assert result["success"]
    assert client.delete_resource.call_args.kwargs == {"TypeName": "AWS::SQS::Queue", "Identifier": "my-queue"}


def test_run_executor_wires_cloud_control_tools_only_when_enabled():
    captured = {}

    def fake_loop(system_prompt, messages, tool_config, tool_handlers, provider=None):
        captured["tools"] = {t["toolSpec"]["name"] for t in tool_config["tools"]}
        captured["handlers"] = set(tool_handlers)
        return {"text": "", "messages": []}

    cc_names = {"create_resource_by_type", "get_resource_by_type", "list_resources_by_type", "delete_resource_by_type"}

    with patch.object(executor, "run_tool_loop", side_effect=fake_loop):
        executor.run_executor({"plan": []}, allow_destructive=True, use_cloud_control=True)
    assert cc_names <= captured["tools"]
    assert cc_names <= captured["handlers"]   # every advertised CC tool has a handler

    captured.clear()
    with patch.object(executor, "run_tool_loop", side_effect=fake_loop):
        executor.run_executor({"plan": []}, allow_destructive=True, use_cloud_control=False)
    assert not (cc_names & captured["tools"])  # off by default
