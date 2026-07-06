"""Tests for the shared read-only inspection tools (moved out of architect.py;
now used by both the Requirements and Architect agents)."""
from unittest.mock import MagicMock, patch

from agents import inspection


def _call_handler(name, params, session=None):
    handlers = {n: (lambda p, fn=fn: fn(p, session)) for n, fn in inspection._HANDLER_FUNCS.items()}
    return handlers[name](params)


def test_list_resources_delegates_to_aws_dispatch():
    with patch("providers.aws_dispatch.list_resources", return_value={"Buckets": [{"Name": "b1"}]}) as mocked:
        result = _call_handler("list_resources", {"resource_type": "s3_bucket"})
    mocked.assert_called_once_with("s3_bucket", None)
    assert result == {"Buckets": [{"Name": "b1"}]}


def test_get_resource_status_delegates_to_aws_dispatch():
    with patch("providers.aws_dispatch.get_resource_status", return_value={"Table": {"TableStatus": "ACTIVE"}}) as mocked:
        result = _call_handler("get_resource_status", {"resource_type": "dynamodb_table", "resource_id": "t1"})
    mocked.assert_called_once_with("dynamodb_table", "t1", None)
    assert result == {"Table": {"TableStatus": "ACTIVE"}}


def test_get_account_info_uses_session_region_when_present():
    sts_mock = MagicMock()
    sts_mock.get_caller_identity.return_value = {"Account": "123456789012", "Arn": "arn:aws:iam::123456789012:user/me"}
    fake_session = MagicMock()
    fake_session.region_name = "eu-west-1"

    with patch("agents.inspection.get_sts_client", return_value=sts_mock):
        result = _call_handler("get_account_info", {}, session=fake_session)

    assert result == {"account_id": "123456789012", "arn": "arn:aws:iam::123456789012:user/me", "region": "eu-west-1"}


def test_get_account_info_falls_back_to_env_region_with_no_session():
    sts_mock = MagicMock()
    sts_mock.get_caller_identity.return_value = {"Account": "1", "Arn": "arn:1"}
    with patch("agents.inspection.get_sts_client", return_value=sts_mock):
        result = _call_handler("get_account_info", {}, session=None)
    assert result["region"]  # falls back to AWS_REGION/default, never crashes with no session


def test_tool_config_resource_type_enum_matches_registry():
    enum_values = inspection.INSPECTION_TOOL_CONFIG["tools"][0]["toolSpec"]["inputSchema"]["json"]["properties"]["resource_type"]["enum"]
    assert set(enum_values) == set(inspection._RESOURCE_TYPE_ENUM)
