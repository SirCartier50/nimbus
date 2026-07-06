from unittest.mock import MagicMock, patch

import pytest

from agents import bodyguard


@pytest.fixture(autouse=True)
def _clean_state():
    bodyguard.state.clear()
    yield
    bodyguard.state.clear()


def test_per_user_state_is_isolated():
    state_a = bodyguard._get_user_state("user-A")
    state_b = bodyguard._get_user_state("user-B")

    bodyguard._log(state_a, "A did something")
    bodyguard._alert(state_a, "A alert", "warning")

    assert state_a["logs"] and not state_b["logs"]
    assert state_a["alerts"] and not state_b["alerts"]


def test_lazy_state_creation_for_never_patrolled_user():
    fresh = bodyguard._get_user_state("user-never-seen")
    assert fresh == {
        "last_check": None,
        "instances_stopped": 0,
        "logs": [],
        "alerts": [],
        "sub_resources": {"volumes": [], "elastic_ips": [], "snapshots": []},
    }


def test_get_status_and_get_alerts_are_scoped_per_user():
    state_a = bodyguard._get_user_state("user-A")
    bodyguard._alert(state_a, "A alert")

    assert len(bodyguard.get_alerts("user-A")) == 1
    assert len(bodyguard.get_alerts("user-B")) == 0
    assert bodyguard.get_status("user-A")["recent_logs"] == []
    assert bodyguard.get_status("user-B")["unread_alerts"] == []


def test_mark_alert_read_does_not_cross_contaminate_users():
    state_a = bodyguard._get_user_state("user-A")
    bodyguard._alert(state_a, "A alert")
    alert_id = state_a["alerts"][0]["id"]

    bodyguard.mark_alert_read("user-B", alert_id)  # different user, same alert id never exists there
    assert state_a["alerts"][0]["read"] is False

    bodyguard.mark_alert_read("user-A", alert_id)
    assert state_a["alerts"][0]["read"] is True


def test_run_patrol_falls_back_per_user_on_bedrock_failure():
    state_a = bodyguard._get_user_state("user-A")
    ec2_mock = MagicMock()
    ec2_mock.describe_instances.return_value = {"Reservations": []}

    with patch("agents.bodyguard.get_ec2_client", return_value=ec2_mock), \
         patch("agents.bodyguard.run_tool_loop", side_effect=Exception("Bedrock down")):
        bodyguard._run_patrol(MagicMock(), state_a)

    assert any("Fallback patrol" in e["message"] for e in state_a["logs"])
    ec2_mock.describe_instances.assert_called_once()


def test_fallback_patrol_alerts_on_non_free_tier_running_instance():
    state_a = bodyguard._get_user_state("user-A")
    ec2_mock = MagicMock()
    ec2_mock.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-1",
                        "InstanceType": "m5.xlarge",
                        "State": {"Name": "running"},
                        "Tags": [],
                    }
                ]
            }
        ]
    }

    with patch("agents.bodyguard.get_ec2_client", return_value=ec2_mock):
        bodyguard._fallback_patrol(MagicMock(), state_a)

    assert any("Non-free-tier" in a["message"] for a in state_a["alerts"])


def test_build_handlers_binds_session_and_user_state_distinctly():
    state_a = bodyguard._get_user_state("user-A")
    state_b = bodyguard._get_user_state("user-B")
    session_a, session_b = MagicMock(), MagicMock()

    handlers_a = bodyguard._build_handlers(session_a, state_a)
    handlers_b = bodyguard._build_handlers(session_b, state_b)

    handlers_a["create_alert"]({"message": "from A"})
    handlers_b["create_alert"]({"message": "from B"})

    assert [a["message"] for a in state_a["alerts"]] == ["from A"]
    assert [a["message"] for a in state_b["alerts"]] == ["from B"]
