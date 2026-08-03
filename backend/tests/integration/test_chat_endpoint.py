"""Integration tests for /api/chat against the real app + DB.

The pipeline front door is the Requirements agent: a plain question is answered
there (no spec), and a build request completes intake (returns a spec) which the
orchestrator then hands to the Architect to propose a plan. These tests mock the
agent functions where the orchestrator imports them (pipeline.orchestrator.*)."""
import json
from unittest.mock import patch

import pytest
from sqlalchemy import select

from db.models import Deployment, Session as SessionModel
from tests.conftest import requires_db

pytestmark = requires_db


def _req(text="...", spec=None, messages=None):
    return {"text": text, "spec": spec, "messages": messages if messages is not None else []}


def _arch(text="...", plan=None, messages=None):
    return {"success": True, "text": text, "plan": plan, "messages": messages if messages is not None else []}


_NO_CRITIQUE = {"blocking_issues": [], "suggestions": []}


@pytest.mark.asyncio
async def test_chat_conversational_response_creates_session(client, db_session):
    req_messages = [{"role": "user", "content": [{"text": "how many instances?"}]}]
    requirements_result = _req(text="You have 2 EC2 instances running.", spec=None, messages=req_messages)

    with patch("pipeline.orchestrator.run_requirements", return_value=requirements_result) as mocked:
        resp = await client.post("/api/chat", json={"message": "how many instances?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["content"] == "You have 2 EC2 instances running."
    assert body["awaiting_confirmation"] is False
    mocked.assert_called_once()

    result = await db_session.execute(select(SessionModel))
    sessions = result.scalars().all()
    assert len(sessions) == 1
    assert sessions[0].history == req_messages


@pytest.mark.asyncio
async def test_chat_with_plan_sets_pending_plan_and_asks_for_confirmation(client, db_session):
    plan = {
        "explanation": "Here's the plan",
        "plan": [{"step": 1, "action": "create", "resource_type": "ec2_instance", "config": {}, "description": "Create EC2"}],
        "cost_warning": "",
    }
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec={"intent": "a server"})), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(text="I'll build this:", plan=plan)), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        resp = await client.post("/api/chat", json={"message": "build me an EC2 instance"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["awaiting_confirmation"] is True
    # finalize_node overwrites/adds estimated_monthly_cost + cost_breakdown with the
    # real computed cost — the architect's own fields pass through unchanged.
    assert body["plan"]["explanation"] == plan["explanation"]
    assert body["plan"]["plan"] == plan["plan"]
    assert "estimated_monthly_cost" in body["plan"]
    assert "Shall I go ahead?" in body["content"]

    result = await db_session.execute(select(SessionModel))
    session = result.scalars().one()
    assert session.pending_plan["plan"] == plan["plan"]
    assert session.plan_is_destructive is False


@pytest.mark.asyncio
async def test_chat_confirm_yes_executes_plan_and_records_deployment(client, db_session):
    plan = {"plan": [{"step": 1, "action": "create", "resource_type": "s3_bucket", "config": {"Bucket": "x"}}]}

    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec={"intent": "a bucket"})), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(text="Plan ready", plan=plan)), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        first = await client.post("/api/chat", json={"message": "make a bucket"})
    session_id = first.json()["session_id"]

    exec_result = {
        "text": "Created S3 bucket.",
        "results": [{"success": True, "resource_type": "s3_bucket", "resource_id": "my-bucket", "name": "my-bucket"}],
    }
    with patch("pipeline.orchestrator.run_executor", return_value=exec_result) as mocked_exec, \
         patch("pipeline.orchestrator.run_validator", return_value=[]), \
         patch("pipeline.orchestrator.run_summary", return_value="Created S3 bucket."):
        resp = await client.post("/api/chat", json={"message": "yes", "session_id": session_id, "confirm": True})

    assert resp.status_code == 200
    body = resp.json()
    # generate_files() always produces a manifest/setup/teardown/readme for any
    # successful result, and chat.py appends a "N config file(s) generated" note —
    # so the executor's own text is a prefix, not the full content.
    assert body["content"].startswith("Created S3 bucket.")
    assert "config file(s) generated" in body["content"]
    assert body["execution_results"] == exec_result["results"]
    mocked_exec.assert_called_once()

    result = await db_session.execute(select(Deployment))
    deployment = result.scalars().one()
    assert deployment.status == "success"
    assert deployment.results == exec_result["results"]

    result = await db_session.execute(select(SessionModel).where(SessionModel.id == deployment.session_id))
    session = result.scalars().one()
    assert session.pending_plan is None


@pytest.mark.asyncio
async def test_chat_confirm_no_cancels_plan_without_executing(client, db_session):
    plan = {"plan": [{"step": 1, "action": "delete", "resource_type": "ec2_instance", "resource_id": "i-1"}]}

    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec={"intent": "remove instance"})), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(text="Plan ready", plan=plan)), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        first = await client.post("/api/chat", json={"message": "delete my instance"})
    session_id = first.json()["session_id"]

    with patch("pipeline.orchestrator.run_executor") as mocked_exec:
        resp = await client.post("/api/chat", json={"message": "no", "session_id": session_id, "confirm": False})

    assert resp.status_code == 200
    assert "cancelled" in resp.json()["content"].lower()
    mocked_exec.assert_not_called()

    result = await db_session.execute(select(SessionModel))
    session = result.scalars().one()
    assert session.pending_plan is None
    assert session.plan_is_destructive is False


@pytest.mark.asyncio
async def test_chat_destructive_plan_flagged_in_response_and_db(client, db_session):
    plan = {"plan": [{"step": 1, "action": "delete", "resource_type": "s3_bucket", "resource_id": "my-bucket"}]}

    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec={"intent": "delete bucket"})), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(text="This will delete your bucket", plan=plan)), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        resp = await client.post("/api/chat", json={"message": "delete my bucket"})

    assert "cannot be undone" in resp.json()["content"]

    result = await db_session.execute(select(SessionModel))
    session = result.scalars().one()
    assert session.plan_is_destructive is True


@pytest.mark.asyncio
async def test_unowned_session_id_starts_fresh_session_instead_of_404(client):
    """Security-relevant: a session_id that doesn't belong to this user must
    silently start a new session, not leak whether that id exists for someone else."""
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hello", spec=None)):
        resp = await client.post(
            "/api/chat", json={"message": "hi", "session_id": "00000000-0000-0000-0000-000000000000"}
        )

    assert resp.status_code == 200
    assert resp.json()["session_id"] != "00000000-0000-0000-0000-000000000000"


@pytest.mark.asyncio
async def test_chat_stream_emits_progress_events_then_final(client, db_session):
    plan = {"plan": [{"step": 1, "action": "create", "resource_type": "s3_bucket", "config": {}}]}
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec={"intent": "a bucket"})), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(text="Plan ready", plan=plan)), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        events = []
        async with client.stream("POST", "/api/chat/stream", json={"message": "make a bucket"}) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))

    stages = [e["stage"] for e in events if e["type"] == "progress"]
    assert stages[:2] == ["requirements", "architect"]     # live per-agent progress
    final = next(e for e in events if e["type"] == "final")
    assert final["awaiting_confirmation"] is True
    assert "Shall I go ahead?" in final["content"]

    result = await db_session.execute(select(SessionModel))
    # finalize_node adds estimated_monthly_cost/cost_breakdown on top — the steps
    # the architect proposed persist unchanged.
    assert result.scalars().one().pending_plan["plan"] == plan["plan"]  # streamed turn still persists


@pytest.mark.asyncio
async def test_chat_requires_auth_header():
    """Sanity check that the real auth middleware still runs in tests (only
    Clerk's network JWKS verification is mocked, not the gate itself)."""
    from httpx import ASGITransport, AsyncClient

    import main

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as unauthenticated_client:
        resp = await unauthenticated_client.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_pipeline_value_error_returns_clean_400_not_a_broken_connection(client):
    """Regression: an unhandled exception here previously propagated all the way
    out of the ASGI app instead of forming a normal HTTP response — which the
    browser reports as a generic network failure ("Failed to fetch"), not a
    status code the frontend can show a real message for. Reproduced by mocking
    an unconfigured LLM provider (ValueError("OPENROUTER_API_KEY is not set")),
    the actual real-world trigger — the fix must catch it and always return JSON."""
    with patch("pipeline.orchestrator.run_requirements", side_effect=ValueError("OPENROUTER_API_KEY is not set")):
        resp = await client.post(
            "/api/chat",
            json={"message": "hi", "provider": "openrouter"},
            headers={"Origin": "http://localhost:3000"},
        )

    assert resp.status_code == 400
    assert resp.json() == {"detail": "OPENROUTER_API_KEY is not set"}
    # Confirms the CORS middleware actually saw a normal response, not an exception
    # unwinding past it (which is what dropped the header in the unfixed version).
    assert "access-control-allow-origin" in resp.headers


@pytest.mark.asyncio
async def test_pipeline_unexpected_error_returns_generic_500_not_raw_internals(client):
    with patch("pipeline.orchestrator.run_requirements", side_effect=RuntimeError("some internal traceback detail")):
        resp = await client.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 500
    assert resp.json() == {"detail": "Something went wrong processing your request. Please try again."}


@pytest.mark.asyncio
async def test_new_session_is_auto_titled_from_first_message(client, db_session):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hi!", spec=None)):
        await client.post("/api/chat", json={"message": "  I need a REST API   with a database  "})

    session = (await db_session.execute(select(SessionModel))).scalars().one()
    # collapsed whitespace, not the raw (padded) message
    assert session.title == "I need a REST API with a database"
    assert session.model == "openrouter"  # default when no provider is chosen (bedrock removed)


@pytest.mark.asyncio
async def test_conversation_turn_appends_to_ui_messages(client, db_session):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Sure, tell me more.", spec=None)):
        await client.post("/api/chat", json={"message": "hello there"})

    session = (await db_session.execute(select(SessionModel))).scalars().one()
    assert len(session.ui_messages) == 2
    assert session.ui_messages[0]["role"] == "user"
    assert session.ui_messages[0]["content"] == "hello there"
    assert session.ui_messages[1] == {
        "role": "assistant",
        "content": "Sure, tell me more.",
        "awaiting_confirmation": False,
        "plan": None,
        "execution_results": None,
        "generated_files": None,
        "timestamp": session.ui_messages[1]["timestamp"],
    }


@pytest.mark.asyncio
async def test_provider_choice_is_passed_through_to_agents_and_stored(client, db_session):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hi!", spec=None)) as mocked:
        resp = await client.post("/api/chat", json={"message": "hi", "provider": "groq"})

    assert resp.status_code == 200
    assert mocked.call_args.kwargs["provider"] == "groq"
    session = (await db_session.execute(select(SessionModel))).scalars().one()
    assert session.model == "groq"


@pytest.mark.asyncio
async def test_list_providers_reflects_which_keys_are_actually_set(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "y")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)

    resp = await client.get("/api/chat/providers")

    assert resp.status_code == 200
    assert resp.json() == {
        "providers": {"groq": True, "openrouter": True, "huggingface": False}
    }


@pytest.mark.asyncio
async def test_unknown_provider_falls_back_to_default_instead_of_crashing(client):
    with patch("pipeline.orchestrator.run_requirements", return_value=_req(text="Hi!", spec=None)) as mocked:
        resp = await client.post("/api/chat", json={"message": "hi", "provider": "not-a-real-provider"})

    assert resp.status_code == 200
    assert mocked.call_args.kwargs["provider"] is None


@pytest.mark.asyncio
async def test_confirm_yes_records_yes_deploy_not_raw_confirm_text_in_ui_messages(client, db_session):
    plan = {"plan": [{"step": 1, "action": "create", "resource_type": "s3_bucket", "config": {"Bucket": "x"}}]}

    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec={"intent": "a bucket"})), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(text="Plan ready", plan=plan)), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        first = await client.post("/api/chat", json={"message": "make a bucket"})
    session_id = first.json()["session_id"]

    exec_result = {"text": "Created.", "results": [{"success": True, "resource_type": "s3_bucket"}]}
    with patch("pipeline.orchestrator.run_executor", return_value=exec_result), \
         patch("pipeline.orchestrator.run_validator", return_value=[]), \
         patch("pipeline.orchestrator.run_summary", return_value="Created."):
        await client.post("/api/chat", json={"message": "yes", "session_id": session_id, "confirm": True})

    session = (await db_session.execute(select(SessionModel))).scalars().one()
    assert len(session.ui_messages) == 4  # 2 turns x (user + assistant)
    assert session.ui_messages[2]["role"] == "user"
    assert session.ui_messages[2]["content"] == "Yes, deploy"  # not the raw "yes"


@pytest.mark.asyncio
async def test_get_files_reads_from_db_not_a_temp_workspace_dir(client):
    """Regression: file delivery must not depend on the deleted routes/workspace.py
    temp directory — it never did (the frontend downloads generated_files straight
    from the JSON response), but this pins that down explicitly."""
    plan = {"plan": [{"step": 1, "action": "create", "resource_type": "s3_bucket", "config": {"Bucket": "x"}}]}

    with patch("pipeline.orchestrator.run_requirements", return_value=_req(spec={"intent": "a bucket"})), \
         patch("pipeline.orchestrator.run_architect", return_value=_arch(text="Plan ready", plan=plan)), \
         patch("pipeline.orchestrator.run_critic", return_value=_NO_CRITIQUE):
        first = await client.post("/api/chat", json={"message": "make a bucket"})
    session_id = first.json()["session_id"]

    exec_result = {"text": "Created.", "results": [{"success": True, "resource_type": "s3_bucket"}]}
    with patch("pipeline.orchestrator.run_executor", return_value=exec_result), \
         patch("pipeline.orchestrator.run_validator", return_value=[]), \
         patch("pipeline.orchestrator.run_summary", return_value="Created."), \
         patch("pipeline.orchestrator.generate_files", return_value={"terraform/main.tf": "resource ..."}):
        await client.post("/api/chat", json={"message": "yes", "session_id": session_id, "confirm": True})

    resp = await client.get(f"/api/files/{session_id}")
    assert resp.json() == {"files": {"terraform/main.tf": "resource ..."}}
