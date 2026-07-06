import botocore.session
import pytest

from providers import aws_registry as registry

SESSION = botocore.session.get_session()


def test_registry_has_fifteen_resource_types():
    assert len(registry.REGISTRY) == 15


@pytest.mark.parametrize("resource_type,spec", list(registry.REGISTRY.items()))
def test_every_spec_resolves_real_botocore_operations(resource_type, spec):
    """Every operation name in the registry must exist in the installed
    botocore service model — this is what would break if AWS renamed an
    operation or we typo'd one, and it's the entire point of sourcing from
    botocore instead of hand-writing these."""
    service_model = SESSION.get_service_model(spec.service)
    service_model.operation_model(spec.create_operation)
    service_model.operation_model(spec.describe_operation)
    service_model.operation_model(spec.delete_operation)
    if spec.list_operation:
        service_model.operation_model(spec.list_operation)


def test_ec2_tag_spec_merge_adds_resource_type_wrapper():
    config = registry.merge_tags_into_config(
        "ec2_instance", {"ImageId": "ami-1"}, {"ManagedBy": "Nimbus", "Name": "foo"}
    )
    assert config["TagSpecifications"] == [
        {"ResourceType": "instance", "Tags": [{"Key": "ManagedBy", "Value": "Nimbus"}, {"Key": "Name", "Value": "foo"}]}
    ]


def test_list_kv_capitalized_merge_rds():
    config = registry.merge_tags_into_config("rds_instance", {"Engine": "mysql"}, {"ManagedBy": "Nimbus"})
    assert config["Tags"] == [{"Key": "ManagedBy", "Value": "Nimbus"}]


def test_list_kv_lowercase_merge_ecs():
    config = registry.merge_tags_into_config("ecs_cluster", {}, {"ManagedBy": "Nimbus"})
    assert config["tags"] == [{"key": "ManagedBy", "value": "Nimbus"}]


def test_map_merge_lambda():
    config = registry.merge_tags_into_config("lambda_function", {}, {"ManagedBy": "Nimbus"})
    assert config["Tags"] == {"ManagedBy": "Nimbus"}


def test_post_create_strategies_are_noop_at_create_time():
    assert registry.merge_tags_into_config("s3_bucket", {"Bucket": "x"}, {"ManagedBy": "Nimbus"}) == {"Bucket": "x"}
    assert registry.merge_tags_into_config("cloudfront", {"a": 1}, {"ManagedBy": "Nimbus"}) == {"a": 1}


def test_post_create_tag_call_s3():
    call = registry.get_post_create_tag_call("s3_bucket", {}, "my-bucket", {"ManagedBy": "Nimbus"})
    assert call == {
        "operation": "PutBucketTagging",
        "params": {"Bucket": "my-bucket", "Tagging": {"TagSet": [{"Key": "ManagedBy", "Value": "Nimbus"}]}},
    }


def test_post_create_tag_call_cloudfront_uses_arn_not_id():
    """CloudFront's TagResource needs the distribution ARN, not the Id that
    extract_resource_id() returns — this is the one resource where those differ."""
    create_response = {"Distribution": {"Id": "DIST123", "ARN": "arn:aws:cloudfront::123:distribution/DIST123"}}
    call = registry.get_post_create_tag_call("cloudfront", create_response, "DIST123", {"ManagedBy": "Nimbus"})
    assert call["params"]["Resource"] == "arn:aws:cloudfront::123:distribution/DIST123"


def test_post_create_tag_call_none_for_create_time_strategies():
    assert registry.get_post_create_tag_call("ec2_instance", {}, "i-123", {}) is None


@pytest.mark.parametrize(
    "resource_type,create_response,input_params,expected",
    [
        ("vpc", {"Vpc": {"VpcId": "vpc-1"}}, {}, "vpc-1"),
        ("ec2_instance", {"Instances": [{"InstanceId": "i-1"}]}, {}, "i-1"),
        ("s3_bucket", {}, {"Bucket": "my-bucket"}, "my-bucket"),
        ("ecs_cluster", {"cluster": {"clusterArn": "arn:aws:ecs:::cluster/x"}}, {}, "arn:aws:ecs:::cluster/x"),
    ],
)
def test_extract_resource_id(resource_type, create_response, input_params, expected):
    assert registry.extract_resource_id(resource_type, create_response, input_params) == expected


def test_describe_vs_delete_id_shape_differs_for_vpc():
    """The whole reason this registry exists instead of one generic shape:
    DescribeVpcs takes a list, DeleteVpc takes a singular id."""
    assert registry.build_id_kwargs("vpc", "vpc-1", "describe") == {"VpcIds": ["vpc-1"]}
    assert registry.build_id_kwargs("vpc", "vpc-1", "delete") == {"VpcId": "vpc-1"}


def test_describe_and_delete_both_use_list_for_ec2_instance():
    """EC2 instances are the exception within EC2 itself: both describe and
    terminate take InstanceIds (list), unlike Vpc/Subnet/SecurityGroup/NatGateway."""
    assert registry.build_id_kwargs("ec2_instance", "i-1", "describe") == {"InstanceIds": ["i-1"]}
    assert registry.build_id_kwargs("ec2_instance", "i-1", "delete") == {"InstanceIds": ["i-1"]}


def test_ecs_uses_lowercase_singular_for_delete():
    assert registry.build_id_kwargs("ecs_cluster", "my-cluster", "delete") == {"cluster": "my-cluster"}
