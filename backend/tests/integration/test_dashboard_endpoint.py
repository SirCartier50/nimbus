from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from agents import bodyguard
from db.models import User
from routes.dashboard import clear_dashboard_cache
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture(autouse=True)
def _clean_bodyguard_state():
    bodyguard.state.clear()
    clear_dashboard_cache()
    yield
    bodyguard.state.clear()
    clear_dashboard_cache()


def _mock_ec2():
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {
                        "InstanceId": "i-1",
                        "InstanceType": "t2.micro",
                        "State": {"Name": "running"},
                        "Tags": [{"Key": "Name", "Value": "my-instance"}, {"Key": "ManagedBy", "Value": "Nimbus"}],
                    }
                ]
            }
        ]
    }
    return ec2


@pytest.mark.asyncio
async def test_dashboard_returns_ec2_resources_and_bodyguard_status(client):
    with patch("routes.dashboard.get_ec2_client", return_value=_mock_ec2()), \
         patch("routes.dashboard.get_s3_client", return_value=MagicMock(list_buckets=lambda: {"Buckets": []})), \
         patch("routes.dashboard.get_dynamodb_client", return_value=MagicMock(list_tables=lambda: {"TableNames": []})), \
         patch("routes.dashboard.get_lambda_client", return_value=MagicMock(list_functions=lambda: {"Functions": []})):
        resp = await client.get("/api/dashboard")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ec2"] == [
        {
            "id": "i-1",
            "name": "my-instance",
            "type": "t2.micro",
            "state": "running",
            "public_ip": None,
            "launch_time": None,
            "resource_type": "ec2",
        }
    ]
    assert body["bodyguard"]["running"] is False  # daemon not started in tests (no lifespan)
    assert body["bodyguard"]["unread_alerts"] == []


@pytest.mark.asyncio
async def test_dashboard_second_call_within_ttl_skips_aws_entirely(client):
    """The whole point of the cache: a second request within the TTL window must
    not call AWS again — this is what makes the frontend's 8s poll interval cheap."""
    ec2 = _mock_ec2()
    with patch("routes.dashboard.get_ec2_client", return_value=ec2), \
         patch("routes.dashboard.get_s3_client", return_value=MagicMock(list_buckets=lambda: {"Buckets": []})), \
         patch("routes.dashboard.get_dynamodb_client", return_value=MagicMock(list_tables=lambda: {"TableNames": []})), \
         patch("routes.dashboard.get_lambda_client", return_value=MagicMock(list_functions=lambda: {"Functions": []})):
        first = await client.get("/api/dashboard")
        second = await client.get("/api/dashboard")

    assert first.json() == second.json()
    assert ec2.describe_instances.call_count == 1


@pytest.mark.asyncio
async def test_dashboard_alerts_are_scoped_to_the_authenticated_user(client):
    """Different Clerk user_ids must never see each other's bodyguard alerts —
    this seeds state for an unrelated user and confirms it stays invisible."""
    bodyguard._get_user_state("some-other-user-id")
    bodyguard._alert(bodyguard._get_user_state("some-other-user-id"), "someone else's alert")

    resp = await client.get("/api/dashboard/alerts")
    assert resp.status_code == 200
    assert resp.json() == {"alerts": []}


@pytest.mark.asyncio
async def test_mark_alert_read_only_affects_calling_users_alerts(client, db_session):
    # bodyguard keys state by the internal User.id (UUID), not the Clerk sub —
    # trigger user creation first so we can seed the alert under the real key
    # the route will actually use.
    await client.get("/api/settings/aws")
    result = await db_session.execute(select(User))
    user = result.scalars().one()

    my_state = bodyguard._get_user_state(str(user.id))
    bodyguard._alert(my_state, "my alert")
    alert_id = my_state["alerts"][0]["id"]

    resp = await client.post("/api/dashboard/alerts/read", json={"alert_id": alert_id})
    assert resp.status_code == 200
    assert my_state["alerts"][0]["read"] is True


@pytest.mark.asyncio
async def test_cost_details_for_running_free_tier_ec2_instance(client):
    ec2 = MagicMock()
    ec2.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"InstanceId": "i-1", "State": {"Name": "running"}, "InstanceType": "t2.micro"}]}]
    }

    with patch("routes.dashboard.get_ec2_client", return_value=ec2):
        resp = await client.get("/api/dashboard/cost-details/ec2/i-1")

    assert resp.status_code == 200
    body = resp.json()
    assert any("free tier" in c["note"].lower() for c in body["costs"])
    assert body["total_monthly"] == 0.0
