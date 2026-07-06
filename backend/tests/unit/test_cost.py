"""Cost estimation — static-table path (no session) and live-pricing path (mocked)."""
from unittest.mock import MagicMock, patch

from pipeline.cost import estimate_plan_cost


def _plan(*steps):
    return {"plan": [{"action": "create", **s} for s in steps]}


def test_free_resources_are_zero():
    cost = estimate_plan_cost(_plan({"resource_type": "vpc", "config": {}}), free_tier_mode=False)
    assert cost["total_monthly"] == 0.0
    assert cost["formatted"] == "$0.00/month (free)"


def test_ec2_micro_is_free_in_free_tier_but_charged_otherwise():
    p = _plan({"resource_type": "ec2_instance", "config": {"InstanceType": "t3.micro"}})
    assert estimate_plan_cost(p, free_tier_mode=True)["total_monthly"] == 0.0
    assert estimate_plan_cost(p, free_tier_mode=False)["total_monthly"] > 0.0


def test_ec2_large_uses_price_table():
    p = _plan({"resource_type": "ec2_instance", "config": {"InstanceType": "m5.large"}})
    cost = estimate_plan_cost(p, free_tier_mode=True)
    assert round(0.096 * 730, 2) == cost["total_monthly"]


def test_nat_gateway_hourly_cost():
    cost = estimate_plan_cost(_plan({"resource_type": "nat_gateway", "config": {}}), free_tier_mode=False)
    assert cost["total_monthly"] == round(0.045 * 730, 2)


def test_usage_based_resource_reports_note_and_marker():
    cost = estimate_plan_cost(_plan({"resource_type": "s3_bucket", "config": {}}), free_tier_mode=True)
    assert cost["total_monthly"] == 0.0
    assert "usage-based" in cost["formatted"]
    assert cost["breakdown"][0]["note"].startswith("usage-based")


def test_rds_flat_monthly():
    cost = estimate_plan_cost(_plan({"resource_type": "rds_instance", "config": {}}), free_tier_mode=False)
    assert cost["total_monthly"] == 15.0


def test_total_sums_multiple_steps():
    p = _plan(
        {"resource_type": "vpc", "config": {}},
        {"resource_type": "nat_gateway", "config": {}},
        {"resource_type": "rds_instance", "config": {}},
    )
    cost = estimate_plan_cost(p, free_tier_mode=False)
    assert cost["total_monthly"] == round(0.045 * 730, 2) + 15.0
    assert len(cost["breakdown"]) == 3


def test_delete_step_has_no_ongoing_cost():
    plan = {"plan": [{"action": "delete", "resource_type": "rds_instance", "resource_id": "db1"}]}
    assert estimate_plan_cost(plan, free_tier_mode=False)["total_monthly"] == 0.0


def test_generic_cfn_type_is_reported_as_unestimated_not_fabricated():
    plan = {"plan": [{"action": "create", "resource_type": "AWS::SQS::Queue", "config": {}}]}
    cost = estimate_plan_cost(plan, free_tier_mode=True)
    assert cost["total_monthly"] == 0.0
    assert cost["breakdown"][0]["source"] == "unknown"
    assert "unestimated" in cost["formatted"]     # honest, not a made-up "$5"


def test_no_session_uses_static_table_and_marks_source():
    p = _plan({"resource_type": "ec2_instance", "config": {"InstanceType": "m5.large"}})
    cost = estimate_plan_cost(p, free_tier_mode=False, aws_session=None)
    assert cost["breakdown"][0]["source"] == "static_table"
    assert cost["total_monthly"] == round(0.096 * 730, 2)


def test_live_pricing_used_when_session_present():
    p = _plan({"resource_type": "ec2_instance", "config": {"InstanceType": "m5.large"}})
    session = MagicMock(region_name="us-east-1")
    with patch("pipeline.cost.pricing_api.ec2_monthly", return_value=88.88) as m:
        cost = estimate_plan_cost(p, free_tier_mode=False, aws_session=session)
    m.assert_called_once_with("m5.large", "us-east-1", session)
    assert cost["total_monthly"] == 88.88
    assert cost["breakdown"][0]["source"] == "aws_pricing_api"


def test_live_pricing_falls_back_to_static_when_unavailable():
    p = _plan({"resource_type": "ec2_instance", "config": {"InstanceType": "m5.large"}})
    session = MagicMock(region_name="us-east-1")
    with patch("pipeline.cost.pricing_api.ec2_monthly", return_value=None):
        cost = estimate_plan_cost(p, free_tier_mode=False, aws_session=session)
    assert cost["breakdown"][0]["source"] == "static_table"
    assert cost["total_monthly"] == round(0.096 * 730, 2)


def test_nat_gateway_uses_live_pricing_when_session_present():
    p = _plan({"resource_type": "nat_gateway", "config": {}})
    session = MagicMock(region_name="eu-west-1")
    with patch("pipeline.cost.pricing_api.nat_gateway_monthly", return_value=40.15) as m:
        cost = estimate_plan_cost(p, free_tier_mode=False, aws_session=session)
    m.assert_called_once_with("eu-west-1", session)
    assert cost["total_monthly"] == 40.15
    assert cost["breakdown"][0]["source"] == "aws_pricing_api"


def test_free_tier_ec2_skips_pricing_lookup_entirely():
    p = _plan({"resource_type": "ec2_instance", "config": {"InstanceType": "t3.micro"}})
    session = MagicMock(region_name="us-east-1")
    with patch("pipeline.cost.pricing_api.ec2_monthly") as m:
        cost = estimate_plan_cost(p, free_tier_mode=True, aws_session=session)
    m.assert_not_called()
    assert cost["total_monthly"] == 0.0
    assert cost["breakdown"][0]["source"] == "free-tier"
