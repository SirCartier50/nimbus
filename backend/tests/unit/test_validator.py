"""Post-deploy health validator (boto3 mocked via aws_dispatch)."""
from unittest.mock import patch

from pipeline.validator import run_validator


def test_successful_resource_is_marked_healthy():
    results = [{"success": True, "resource_type": "s3_bucket", "resource_id": "b1"}]
    with patch("providers.aws_dispatch.get_resource_status", return_value={"ok": True}) as m:
        health = run_validator(results, aws_session=None)
    m.assert_called_once_with("s3_bucket", "b1", None)
    assert health == [{"resource_type": "s3_bucket", "resource_id": "b1", "healthy": True}]


def test_describe_failure_marks_unhealthy_with_detail_not_raising():
    results = [{"success": True, "resource_type": "ec2_instance", "resource_id": "i-1"}]
    with patch("providers.aws_dispatch.get_resource_status", side_effect=Exception("not found")):
        health = run_validator(results)
    assert health[0]["healthy"] is False
    assert "not found" in health[0]["detail"]


def test_skips_failed_and_idless_results():
    results = [
        {"success": False, "resource_type": "s3_bucket", "resource_id": "b1"},
        {"success": True, "resource_type": "s3_bucket"},  # no id
        {"success": True, "resource_id": "x"},            # no type
    ]
    with patch("providers.aws_dispatch.get_resource_status") as m:
        health = run_validator(results)
    assert health == []
    m.assert_not_called()
