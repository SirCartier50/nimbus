import asyncio
import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import get_or_create_user
from db.deps import get_db
from db.models import Deployment, Session as SessionModel
from pipeline.orchestrator import run_turn, stream_turn
from pipeline.state import PipelineState
from utils.user_aws import get_user_boto3_session

router = APIRouter()

# Providers a user can pick in the frontend's model selector — kept in sync with
# utils.llm.get_provider()'s accepted names.
KNOWN_PROVIDERS = {"bedrock", "groq", "openrouter", "huggingface"}


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=4000)
    session_id: Optional[str] = None
    confirm: Optional[bool] = None
    free_tier_mode: Optional[bool] = True
    provider: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    role: str
    content: str
    awaiting_confirmation: bool = False
    plan: Optional[dict] = None
    execution_results: Optional[list] = None
    generated_files: Optional[dict] = None


async def _get_owned_session(db: AsyncSession, user_id, session_id: str) -> Optional[SessionModel]:
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        return None
    result = await db.execute(
        select(SessionModel).where(SessionModel.id == sid, SessionModel.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _title_from_message(message: str) -> str:
    collapsed = " ".join(message.split())
    return collapsed[:60] + ("…" if len(collapsed) > 60 else "")


async def _load_session(db: AsyncSession, user, req: ChatRequest) -> SessionModel:
    session = await _get_owned_session(db, user.id, req.session_id) if req.session_id else None
    if session is None:
        # No session_id, or it doesn't belong to this user — start a fresh session
        # rather than 404ing (also avoids leaking whether another user's id exists).
        session = SessionModel(
            user_id=user.id,
            model=req.provider or "bedrock",
            title=_title_from_message(req.message) if req.message else None,
            history=[],
            ui_messages=[],
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return session


def _build_state(user, session, req: ChatRequest, aws_session) -> PipelineState:
    # Rehydrate any pending plan from the session row so a confirmation resumes exactly
    # where the proposal left off.
    return PipelineState(
        user_id=str(user.id),
        session_id=str(session.id),
        user_message=req.message,
        history=session.history or [],
        free_tier_mode=req.free_tier_mode,
        aws_session=aws_session,
        provider=req.provider if req.provider in KNOWN_PROVIDERS else None,
        confirm=req.confirm,
        pending_plan=session.pending_plan,
        plan_is_destructive=session.plan_is_destructive,
    )


def _append_ui_messages(session: SessionModel, state: PipelineState, payload: dict) -> None:
    """Mirror the exact turn the frontend renders into `ui_messages`, so switching
    back to this session later re-renders the same plan cards/results instead of
    just resuming the underlying agent context blind. Reassigned (not mutated
    in-place) so SQLAlchemy's change-tracking on the JSONB column picks it up."""
    if state.confirm is True:
        user_display = "Yes, deploy"
    elif state.confirm is False:
        user_display = "No, cancel"
    else:
        user_display = state.user_message

    now_ms = int(time.time() * 1000)
    session.ui_messages = [
        *(session.ui_messages or []),
        {"role": "user", "content": user_display, "timestamp": now_ms},
        {
            "role": "assistant",
            "content": payload["content"],
            "awaiting_confirmation": payload["awaiting_confirmation"],
            "plan": payload["plan"],
            "execution_results": payload["execution_results"],
            "generated_files": payload["generated_files"],
            "timestamp": now_ms,
        },
    ]


async def _finalize_turn(db: AsyncSession, user, session: SessionModel, state: PipelineState) -> dict:
    """Persist the finished turn and build the response payload. Shared by the plain
    and streaming endpoints so both behave identically off the same `state.outcome`."""
    session_id = str(session.id)

    # --- Plan executed (user confirmed) ---
    if state.outcome == "executed":
        results = state.execution_results or []
        ok = [r for r in results if r.get("success")]
        fail = [r for r in results if not r.get("success")]
        files = state.generated_files or {}

        content = state.display_text
        if files:
            content += f"\n\n{len(files)} config file(s) generated. Use the download button to grab them."

        session.generated_files = files
        session.pending_plan = None
        session.plan_is_destructive = False
        status = "success" if not fail else ("partial" if ok else "failed")
        db.add(Deployment(
            user_id=user.id,
            session_id=session.id,
            plan=state.plan,
            results=results,
            status=status,
        ))
        payload = {
            "session_id": session_id, "role": "assistant", "content": content,
            "awaiting_confirmation": False, "plan": None,
            "execution_results": results, "generated_files": files,
        }
        _append_ui_messages(session, state, payload)
        await db.commit()
        return payload

    # --- Plan cancelled (user declined) ---
    if state.outcome == "cancelled":
        session.pending_plan = None
        session.plan_is_destructive = False
        payload = {
            "session_id": session_id, "role": "assistant", "content": state.display_text,
            "awaiting_confirmation": False, "plan": None,
            "execution_results": None, "generated_files": None,
        }
        _append_ui_messages(session, state, payload)
        await db.commit()
        return payload

    # --- Architect proposed a plan → ask for confirmation ---
    if state.outcome == "plan_proposed":
        session.history = state.history
        session.pending_plan = state.pending_plan
        session.plan_is_destructive = state.plan_is_destructive

        plan = state.plan
        content = state.display_text

        steps_text = "\n".join(
            f"  {i + 1}. {s.get('description', s.get('action', ''))}"
            for i, s in enumerate(plan.get("plan", []))
        )
        estimated = plan.get("estimated_monthly_cost", "$0.00 (free tier)")
        cost_note = plan.get("cost_warning", "")

        content += f"\n\n**Plan:**\n{steps_text}"
        content += f"\n\n**Estimated monthly cost:** {estimated}"
        if cost_note:
            content += f"\n\n⚠️  {cost_note}"
        if state.validation_blocking:
            issues = "\n".join(f"- {i}" for i in state.validation_blocking)
            content += f"\n\n⚠️ **Issues to review:**\n{issues}"
        if state.validation_suggestions:
            suggestions = "\n".join(f"- {s}" for s in state.validation_suggestions)
            content += f"\n\n💡 **Suggestions:**\n{suggestions}"
        if state.plan_is_destructive:
            content += "\n\n🚨 **This plan includes destructive actions that cannot be undone.**"
        content += "\n\nShall I go ahead? Reply **yes** to deploy or **no** to cancel."

        payload = {
            "session_id": session_id, "role": "assistant", "content": content,
            "awaiting_confirmation": True, "plan": plan,
            "execution_results": None, "generated_files": None,
        }
        _append_ui_messages(session, state, payload)
        await db.commit()
        return payload

    # --- Conversational reply (front door answered directly, no plan) ---
    session.history = state.history
    payload = {
        "session_id": session_id, "role": "assistant", "content": state.display_text,
        "awaiting_confirmation": False, "plan": None,
        "execution_results": None, "generated_files": None,
    }
    _append_ui_messages(session, state, payload)
    await db.commit()
    return payload


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    aws_session = await get_user_boto3_session(db, user.id)
    session = await _load_session(db, user, req)
    state = _build_state(user, session, req, aws_session)

    # The agents block on Bedrock/boto3 — run the whole turn in a thread so it
    # doesn't stall the event loop for other concurrent requests.
    #
    # This must never let an exception propagate unhandled: doing so bypasses normal
    # response formation (confirmed — the exception reaches the client as a raw
    # connection failure, not a clean HTTP response), which the browser reports as
    # a generic "Failed to fetch" with no indication anything server-side broke.
    try:
        state = await asyncio.to_thread(run_turn, state)
    except ValueError as e:
        # e.g. the user picked an LLM provider the server isn't configured for —
        # safe to show verbatim, and actionable (pick a different model).
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=500, detail="Something went wrong processing your request. Please try again."
        )

    payload = await _finalize_turn(db, user, session, state)
    return ChatResponse(**payload)


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Same turn as /chat, but streamed as Server-Sent Events: one `progress` event per
    agent as the LangGraph graph advances (live activity feed), then a `final` event
    carrying the full response payload."""
    user = await get_or_create_user(db, request.state.user_id)
    aws_session = await get_user_boto3_session(db, user.id)
    session = await _load_session(db, user, req)
    state = _build_state(user, session, req, aws_session)

    async def sse():
        # stream_turn drives the graph synchronously (blocking Bedrock/boto3 calls);
        # run it in a worker thread and hand progress events back to this event loop
        # via a queue so the SSE stream stays responsive.
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        holder: dict = {}

        def produce():
            try:
                for event in stream_turn(state):
                    if event["type"] == "final":
                        holder["state"] = event["state"]
                    else:
                        loop.call_soon_threadsafe(queue.put_nowait, event)
            except ValueError as e:
                # e.g. the user picked an LLM provider the server isn't configured
                # for — safe to show verbatim, and actionable.
                holder["error"] = str(e)
            except Exception:  # surface agent/graph failures instead of hanging the stream
                holder["error"] = "Something went wrong processing your request. Please try again."
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # done sentinel

        loop.run_in_executor(None, produce)

        while True:
            event = await queue.get()
            if event is None:
                break
            yield _sse(event)

        if "error" in holder:
            yield _sse({"type": "error", "message": f"Sorry, something went wrong: {holder['error']}"})
            return

        payload = await _finalize_turn(db, user, session, holder["state"])
        yield _sse({"type": "final", **payload})

    return StreamingResponse(sse(), media_type="text/event-stream")


@router.get("/files/{session_id}")
async def get_files(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    session = await _get_owned_session(db, user.id, session_id)
    if not session or not session.generated_files:
        return {"files": {}}
    return {"files": session.generated_files}
