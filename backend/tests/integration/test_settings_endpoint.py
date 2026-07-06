from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from db.models import UserSettings
from tests.conftest import requires_db

pytestmark = requires_db


def _assumed_session(account="123456789012", arn="arn:aws:iam::123456789012:role/NimbusAccessRole"):
    sts_mock = MagicMock()
    sts_mock.get_caller_identity.return_value = {"Account": account, "Arn": arn}
    session_mock = MagicMock()
    session_mock.client.return_value = sts_mock
    return session_mock


@pytest.mark.asyncio
async def test_aws_status_disconnected_by_default_but_has_external_id(client, db_session):
    resp = await client.get("/api/settings/aws")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["role_arn"] is None
    assert body["region"] == "us-east-1"
    # external_id is generated + persisted on first view, not a fixed value
    assert isinstance(body["external_id"], str) and len(body["external_id"]) > 0

    result = await db_session.execute(select(UserSettings))
    settings = result.scalars().one()
    assert settings.aws_external_id == body["external_id"]


@pytest.mark.asyncio
async def test_external_id_is_stable_across_repeated_requests(client):
    first = (await client.get("/api/settings/aws")).json()["external_id"]
    second = (await client.get("/api/settings/aws")).json()["external_id"]
    assert first == second


@pytest.mark.asyncio
async def test_connect_aws_role_validates_via_assume_role_and_stores_role_arn(client, db_session):
    role_arn = "arn:aws:iam::123456789012:role/NimbusAccessRole"

    with patch("routes.settings.assume_role", return_value=_assumed_session()) as mocked_assume:
        resp = await client.post("/api/settings/aws", json={"role_arn": role_arn})

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "connected": True,
        "account_id": "123456789012",
        "arn": "arn:aws:iam::123456789012:role/NimbusAccessRole",
        "region": "us-east-1",
    }
    mocked_assume.assert_called_once()
    call_args = mocked_assume.call_args.args
    assert call_args[0] == role_arn  # the role_arn the user submitted

    result = await db_session.execute(select(UserSettings))
    settings = result.scalars().one()
    assert settings.aws_role_arn == role_arn
    assert settings.aws_external_id  # generated as part of the same flow


@pytest.mark.asyncio
async def test_connect_aws_role_rejects_when_assume_role_fails(client):
    with patch("routes.settings.assume_role", side_effect=Exception("AccessDenied")):
        resp = await client.post(
            "/api/settings/aws", json={"role_arn": "arn:aws:iam::123456789012:role/Wrong"}
        )

    assert resp.status_code == 400
    assert "Unable to assume that role" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_aws_status_reflects_connected_state(client):
    role_arn = "arn:aws:iam::123456789012:role/NimbusAccessRole"
    with patch("routes.settings.assume_role", return_value=_assumed_session()):
        await client.post("/api/settings/aws", json={"role_arn": role_arn})

    resp = await client.get("/api/settings/aws")
    body = resp.json()
    assert body["connected"] is True
    assert body["role_arn"] == role_arn


@pytest.mark.asyncio
async def test_github_repo_url_must_be_a_github_url(client):
    resp = await client.post("/api/settings/github", json={"repo_url": "https://gitlab.com/foo/bar"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_set_and_get_github_repo(client):
    resp = await client.post("/api/settings/github", json={"repo_url": "https://github.com/foo/bar"})
    assert resp.status_code == 200
    assert resp.json() == {"connected": True, "repo_url": "https://github.com/foo/bar"}

    resp = await client.get("/api/settings/github")
    assert resp.json() == {"connected": True, "repo_url": "https://github.com/foo/bar"}
