"""Tier-1 deterministic plan validation."""
from pipeline.validation import validate_plan


def test_clean_plan_has_no_issues():
    plan = {"plan": [{"action": "create", "resource_type": "s3_bucket", "config": {"Bucket": "x"}}]}
    assert validate_plan(plan) == []


def test_empty_plan_is_flagged():
    assert validate_plan({"plan": []})
    assert validate_plan({})


def test_unknown_action_and_resource_type_flagged():
    plan = {"plan": [
        {"action": "frobnicate", "resource_type": "s3_bucket"},
        {"action": "create", "resource_type": "quantum_computer", "config": {}},
    ]}
    issues = validate_plan(plan)
    assert any("unknown action" in i for i in issues)
    assert any("unknown resource_type" in i for i in issues)


def test_create_without_config_flagged():
    plan = {"plan": [{"action": "create", "resource_type": "s3_bucket"}]}
    assert any("missing a config" in i for i in validate_plan(plan))


def test_delete_without_resource_id_flagged():
    plan = {"plan": [{"action": "delete", "resource_type": "s3_bucket"}]}
    assert any("missing a resource_id" in i for i in validate_plan(plan))


def test_free_tier_disallowed_resource_flagged_only_in_free_tier():
    plan = {"plan": [{"action": "create", "resource_type": "rds_instance", "config": {}}]}
    assert any("not free-tier eligible" in i for i in validate_plan(plan, free_tier_mode=True))
    assert validate_plan(plan, free_tier_mode=False) == []


def test_free_tier_ec2_instance_type_flagged():
    plan = {"plan": [{"action": "create", "resource_type": "ec2_instance", "config": {"InstanceType": "m5.large"}}]}
    assert any("not free-tier eligible" in i for i in validate_plan(plan, free_tier_mode=True))
    # micro is fine
    ok = {"plan": [{"action": "create", "resource_type": "ec2_instance", "config": {"InstanceType": "t3.micro"}}]}
    assert validate_plan(ok, free_tier_mode=True) == []


def test_prerequisite_ordering_violation_flagged():
    # subnet created before its vpc (both in the plan) → flagged
    plan = {"plan": [
        {"action": "create", "resource_type": "subnet", "config": {}},
        {"action": "create", "resource_type": "vpc", "config": {}},
    ]}
    assert any("before its prerequisite" in i for i in validate_plan(plan, free_tier_mode=False))


def test_prerequisite_absent_from_plan_is_not_flagged():
    # subnet referencing an existing (out-of-plan) vpc is fine
    plan = {"plan": [{"action": "create", "resource_type": "subnet", "config": {"VpcId": "vpc-123"}}]}
    assert validate_plan(plan, free_tier_mode=False) == []


def test_correct_ordering_passes():
    plan = {"plan": [
        {"action": "create", "resource_type": "vpc", "config": {}},
        {"action": "create", "resource_type": "subnet", "config": {}},
    ]}
    assert validate_plan(plan, free_tier_mode=False) == []


# --- generic CloudFormation type names (Cloud Control path) ----------------------


def test_cfn_type_name_accepted_as_generic():
    plan = {"plan": [{"action": "create", "resource_type": "AWS::SQS::Queue", "config": {"QueueName": "q"}}]}
    assert validate_plan(plan, free_tier_mode=True) == []


def test_cfn_type_create_without_config_flagged():
    plan = {"plan": [{"action": "create", "resource_type": "AWS::SQS::Queue"}]}
    assert any("missing a config" in i for i in validate_plan(plan))


def test_cfn_type_delete_without_id_flagged():
    plan = {"plan": [{"action": "delete", "resource_type": "AWS::SQS::Queue"}]}
    assert any("missing a resource_id" in i for i in validate_plan(plan))


def test_unknown_non_cfn_type_still_rejected():
    plan = {"plan": [{"action": "create", "resource_type": "quantum_widget", "config": {}}]}
    assert any("unknown resource_type" in i for i in validate_plan(plan))


def test_free_tier_rules_do_not_apply_to_generic_types():
    # Documents the known gap: Tier-1 can't enforce free-tier on arbitrary CFN types
    # (no per-service knowledge), so this isn't flagged here — the Architect prompt guards it.
    plan = {"plan": [{"action": "create", "resource_type": "AWS::RDS::DBInstance", "config": {}}]}
    assert validate_plan(plan, free_tier_mode=True) == []
