import pytest

from providers.aws_schema import COLLAPSED_DESCRIPTION, generate_tool_schema, generate_validation_schema


def test_top_level_scalars_render_with_real_types_even_at_depth_zero():
    """Regression test for the depth-gating bug: scalar fields used to get
    collapsed into a generic {"type": "object"} placeholder once recursion
    depth ran out, even though they're cheap and should always render fully."""
    schema = generate_tool_schema("ec2", "RunInstances", max_depth=0)
    assert schema["properties"]["ImageId"]["type"] == "string"
    assert schema["properties"]["InstanceType"]["type"] == "string"


def test_enum_values_present_on_vpc_instance_tenancy():
    schema = generate_tool_schema("ec2", "CreateVpc", max_depth=0)
    assert "enum" in schema["properties"]["InstanceTenancy"]
    assert "default" in schema["properties"]["InstanceTenancy"]["enum"]


def test_required_fields_propagate():
    schema = generate_tool_schema("ec2", "RunInstances", max_depth=0)
    assert "MinCount" in schema["required"]
    assert "MaxCount" in schema["required"]


def test_validation_schema_has_no_enum_cap():
    """Tool schema caps long enums to keep the model's context small;
    validation schema must never do that, or real-but-rare values would be
    rejected locally even though AWS would accept them."""
    s3_validation = generate_validation_schema("s3", "CreateBucket")
    region_enum = s3_validation["properties"]["CreateBucketConfiguration"]["properties"]["LocationConstraint"]["enum"]
    assert len(region_enum) > 10


def test_depth_zero_collapses_nested_structures():
    schema = generate_tool_schema("ec2", "RunInstances", max_depth=0)
    placement = schema["properties"]["Placement"]
    assert placement.get("description") == COLLAPSED_DESCRIPTION


def test_deeper_max_depth_uncollapses_nested_structures():
    schema = generate_tool_schema("ec2", "RunInstances", max_depth=2)
    placement = schema["properties"]["Placement"]
    assert "properties" in placement
    assert COLLAPSED_DESCRIPTION not in str(placement)


def test_cloudfront_single_wrapper_field_is_not_left_empty_at_default_depth():
    """CreateDistribution has exactly one top-level field (DistributionConfig)
    holding all the real content — depth=0 used to leave this tool almost
    empty. Confirms the default max_depth=2 actually surfaces real fields."""
    schema = generate_tool_schema("cloudfront", "CreateDistribution")
    dist_config = schema["properties"]["DistributionConfig"]
    assert "properties" in dist_config
    assert len(dist_config["properties"]) > 3
