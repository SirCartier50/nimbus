"""GET /api/sessions, GET /api/sessions/{id} — list/detail for the session switcher.
Sessions are created via /api/chat (mocked at the pipeline.orchestrator level, same
convention as test_chat_endpoint.py) since that's the only way one is ever created."""
from unittest.mock import patch

import pytest

from tests.conftest import requires_db

pytestmark = requires_db


def _req(text="...", spec=None):
    return {"text": text, "spec": spec, "messages": []}


@pytest.mark.asyncio
async def test_list_sessions_empty_by_default(client):
    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json() == {"sessions": [], "total": 0, "has_more": False}


@pytest.mark.asyncio
async def test_list_sessions_orders_most_recently_updated_first(client):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hi!")):
        first = await client.post("/api/chat", json={"message": "first conversation"})
        second = await client.post("/api/chat", json={"message": "second conversation"})

    resp = await client.get("/api/sessions")
    ids = [s["id"] for s in resp.json()["sessions"]]
    assert ids == [second.json()["session_id"], first.json()["session_id"]]


@pytest.mark.asyncio
async def test_list_sessions_includes_title_and_model(client):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hi!")):
        await client.post("/api/chat", json={"message": "build me a website", "provider": "openrouter"})

    resp = await client.get("/api/sessions")
    session = resp.json()["sessions"][0]
    assert session["title"] == "build me a website"
    assert session["model"] == "openrouter"
    assert session["created_at"] and session["updated_at"]


@pytest.mark.asyncio
async def test_session_detail_includes_ui_messages(client):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hello!")):
        resp = await client.post("/api/chat", json={"message": "hello"})
    session_id = resp.json()["session_id"]

    detail = await client.get(f"/api/sessions/{session_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == session_id
    assert body["title"] == "hello"
    assert len(body["messages"]) == 2
    assert body["messages"][0] == {"role": "user", "content": "hello", "timestamp": body["messages"][0]["timestamp"]}
    assert body["messages"][1]["content"] == "Hello!"


@pytest.mark.asyncio
async def test_session_detail_404s_for_unknown_id(client):
    resp = await client.get("/api/sessions/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_session_detail_404s_for_malformed_id(client):
    resp = await client.get("/api/sessions/not-a-uuid")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sessions_are_scoped_to_the_owning_user(client, db_session):
    """A session created under a different clerk user must not be listed or
    fetchable — mirrors the ownership check /api/chat already relies on."""
    import uuid

    from db.models import Session as SessionModel, User

    other_user = User(clerk_user_id="someone-else")
    db_session.add(other_user)
    await db_session.commit()
    other_session = SessionModel(user_id=other_user.id, model="bedrock", title="not yours", history=[], ui_messages=[])
    db_session.add(other_session)
    await db_session.commit()

    resp = await client.get("/api/sessions")
    assert resp.json() == {"sessions": [], "total": 0, "has_more": False}

    detail = await client.get(f"/api/sessions/{other_session.id}")
    assert detail.status_code == 404


@pytest.mark.asyncio
async def test_list_sessions_paginates_with_limit_and_offset(client):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hi!")):
        for i in range(7):
            await client.post("/api/chat", json={"message": f"conversation {i}"})

    first_page = await client.get("/api/sessions", params={"limit": 5})
    body = first_page.json()
    assert len(body["sessions"]) == 5
    assert body["total"] == 7
    assert body["has_more"] is True

    second_page = await client.get("/api/sessions", params={"limit": 5, "offset": 5})
    body2 = second_page.json()
    assert len(body2["sessions"]) == 2
    assert body2["has_more"] is False

    # no overlap between pages
    ids_page1 = {s["id"] for s in body["sessions"]}
    ids_page2 = {s["id"] for s in body2["sessions"]}
    assert ids_page1.isdisjoint(ids_page2)


@pytest.mark.asyncio
async def test_rename_session(client, db_session):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hi!")):
        resp = await client.post("/api/chat", json={"message": "original title"})
    session_id = resp.json()["session_id"]

    rename_resp = await client.patch(f"/api/sessions/{session_id}", json={"title": "My renamed chat"})
    assert rename_resp.status_code == 200
    assert rename_resp.json() == {"id": session_id, "title": "My renamed chat"}

    detail = await client.get(f"/api/sessions/{session_id}")
    assert detail.json()["title"] == "My renamed chat"


@pytest.mark.asyncio
async def test_rename_session_rejects_blank_title(client):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hi!")):
        resp = await client.post("/api/chat", json={"message": "hi"})
    session_id = resp.json()["session_id"]

    rename_resp = await client.patch(f"/api/sessions/{session_id}", json={"title": "   "})
    assert rename_resp.status_code == 400


@pytest.mark.asyncio
async def test_rename_session_404s_for_unowned_session(client, db_session):
    from db.models import Session as SessionModel, User

    other_user = User(clerk_user_id="someone-else-2")
    db_session.add(other_user)
    await db_session.commit()
    other_session = SessionModel(user_id=other_user.id, model="bedrock", title="not yours", history=[], ui_messages=[])
    db_session.add(other_session)
    await db_session.commit()

    resp = await client.patch(f"/api/sessions/{other_session.id}", json={"title": "hijacked"})
    assert resp.status_code == 404
