from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
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


@pytest.fixture
def encryption_key(monkeypatch):
    """utils.secret_box._fernet() is lru_cache'd, so a key set via monkeypatch
    after the first call would be silently ignored — clear it on both sides."""
    import utils.secret_box as secret_box

    monkeypatch.setenv("SETTINGS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    secret_box._fernet.cache_clear()
    yield
    secret_box._fernet.cache_clear()


@pytest.mark.asyncio
async def test_api_keys_all_unconfigured_by_default(client, monkeypatch):
    for var in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "HF_TOKEN", "HUGGINGFACE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    resp = await client.get("/api/settings/api-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"groq", "openrouter", "huggingface"}
    for status in body.values():
        assert status == {"source": None, "configured": False, "masked": None}


@pytest.mark.asyncio
async def test_api_keys_reflects_operator_key_when_no_user_key(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "operator-key")

    resp = await client.get("/api/settings/api-keys")
    body = resp.json()
    assert body["groq"] == {"source": "operator", "configured": True, "masked": None}


@pytest.mark.asyncio
async def test_set_api_key_rejects_unknown_provider(client, encryption_key):
    resp = await client.put("/api/settings/api-keys/bedrock", json={"key": "whatever"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_api_key_fails_closed_without_encryption_key_configured(client, monkeypatch):
    monkeypatch.delenv("SETTINGS_ENCRYPTION_KEY", raising=False)
    import utils.secret_box as secret_box

    secret_box._fernet.cache_clear()

    resp = await client.put("/api/settings/api-keys/groq", json={"key": "gsk_livesecret"})
    assert resp.status_code == 503
    secret_box._fernet.cache_clear()


@pytest.mark.asyncio
async def test_set_get_delete_api_key_round_trip(client, db_session, encryption_key):
    resp = await client.put("/api/settings/api-keys/groq", json={"key": "gsk_livesecret1234"})
    assert resp.status_code == 200
    status = resp.json()["groq"]
    assert status["source"] == "user"
    assert status["configured"] is True
    # Masked, never the plaintext key or its full ciphertext
    assert status["masked"].startswith("····")
    assert "gsk_livesecret1234" not in resp.text

    result = await db_session.execute(select(UserSettings))
    settings = result.scalars().one()
    stored = settings.provider_keys_enc["groq"]
    assert stored != "gsk_livesecret1234"  # encrypted at rest, not the plaintext

    resp = await client.get("/api/settings/api-keys")
    assert resp.json()["groq"]["source"] == "user"

    resp = await client.delete("/api/settings/api-keys/groq")
    assert resp.status_code == 200
    assert resp.json()["groq"] == {"source": None, "configured": False, "masked": None}

    resp = await client.get("/api/settings/api-keys")
    assert resp.json()["groq"]["configured"] is False


@pytest.mark.asyncio
async def test_models_default_to_config_defaults(client):
    from config import MODEL_DEFAULTS

    resp = await client.get("/api/settings/models")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"groq", "openrouter", "huggingface"}
    for provider, default in MODEL_DEFAULTS.items():
        assert body[provider] == {"model": default, "is_custom": False, "default": default}


@pytest.mark.asyncio
async def test_set_model_rejects_unknown_provider(client):
    resp = await client.put("/api/settings/models/bedrock", json={"model": "whatever"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_and_reset_model_round_trip(client, db_session):
    from config import MODEL_DEFAULTS

    resp = await client.put("/api/settings/models/groq", json={"model": "llama-3.1-8b-instant"})
    assert resp.status_code == 200
    assert resp.json()["groq"] == {
        "model": "llama-3.1-8b-instant",
        "is_custom": True,
        "default": MODEL_DEFAULTS["groq"],
    }

    result = await db_session.execute(select(UserSettings))
    settings = result.scalars().one()
    assert settings.provider_models["groq"] == "llama-3.1-8b-instant"

    resp = await client.get("/api/settings/models")
    assert resp.json()["groq"]["is_custom"] is True

    resp = await client.delete("/api/settings/models/groq")
    assert resp.status_code == 200
    assert resp.json()["groq"] == {
        "model": MODEL_DEFAULTS["groq"],
        "is_custom": False,
        "default": MODEL_DEFAULTS["groq"],
    }
