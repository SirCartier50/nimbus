import asyncio
import concurrent.futures
import json
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from budget import consume_daily_turn, seconds_until_utc_midnight
from config import KNOWN_PROVIDERS, operator_key_configured
from db.crud import get_or_create_user, get_user_settings
from db.deps import get_db
from db.engine import async_session_local
from db.models import Deployment, Session as SessionModel
from pipeline.orchestrator import run_turn, stream_turn
from pipeline.state import PipelineState
from utils.llm import get_provider
from utils.secret_box import SecretBoxNotConfigured, decrypt_secret
from utils.user_aws import get_user_boto3_session

router = APIRouter()

# Chat turns block a thread for their full duration (LLM + boto3 are synchronous,
# and a deploy can run for many minutes). They get their OWN bounded executor so
# concurrent turns can never starve the default to_thread pool that everything
# else (dashboard resource fetches, etc.) relies on. The semaphore is the
# admission gate: when every slot is busy, new turns get an immediate 503
# instead of silently queueing behind multi-minute deploys.
MAX_CONCURRENT_TURNS = int(os.getenv("MAX_CONCURRENT_TURNS", "8"))
# Hang guard, not a UX budget — real deploys (e.g. CloudFront) legitimately take
# 15+ minutes; this only exists so a wedged LLM/AWS call can't hold a slot forever.
TURN_TIMEOUT_SECONDS = float(os.getenv("TURN_TIMEOUT_SECONDS", "1800"))

_turn_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_TURNS, thread_name_prefix="turn"
)
_turn_slots = asyncio.Semaphore(MAX_CONCURRENT_TURNS)

_AT_CAPACITY = "The server is handling its maximum number of deployments right now. Please retry in a moment."
_TURN_TIMED_OUT = "The request took too long and was aborted. Please try again."


async def _spend_turn_budget(user) -> None:
    """One chat turn = one unit of daily budget (each fans out to an LLM). 429
    with a reset hint when today's budget is gone — this is the backstop that
    caps worst-case spend per user per day, above the per-minute rate limiter."""
    allowed, _used, limit = await consume_daily_turn(str(user.id))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"You've reached today's limit of {limit} requests. It resets at midnight UTC.",
            headers={"Retry-After": str(seconds_until_utc_midnight())},
        )


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
            model=req.provider or os.getenv("LLM_PROVIDER", "openrouter"),
            title=_title_from_message(req.message) if req.message else None,
            history=[],
            ui_messages=[],
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return session


async def _resolve_provider(db: AsyncSession, user, provider_name: Optional[str]):
    """A string provider name normally reaches get_provider() unresolved and it
    reads the shared operator key/model from the environment. If this user has
    their own key (Settings > API Keys) and/or model override (Settings > Model
    Configurations) for that provider, build the real provider instance here
    instead, so their turn runs on their own key/quota and chosen model. Returns
    the plain name (or None) when there's nothing to swap in — get_provider()
    already knows how to turn that into the operator-default path."""
    if provider_name not in KNOWN_PROVIDERS:
        return provider_name
    settings = await get_user_settings(db, user.id)
    ciphertext = ((settings.provider_keys_enc if settings else None) or {}).get(provider_name)
    model = ((settings.provider_models if settings else None) or {}).get(provider_name)
    if not ciphertext and not model:
        return provider_name
    api_key = None
    if ciphertext:
        try:
            api_key = decrypt_secret(ciphertext)
        except SecretBoxNotConfigured:
            # Encryption key rotated/missing since this was stored — fall back to
            # the operator key rather than failing the whole turn.
            api_key = None
    return get_provider(provider_name, api_key=api_key, model=model)


async def _build_state(db: AsyncSession, user, session, req: ChatRequest, aws_session) -> PipelineState:
    # Rehydrate any pending plan from the session row so a confirmation resumes exactly
    # where the proposal left off.
    provider = await _resolve_provider(db, user, req.provider if req.provider in KNOWN_PROVIDERS else None)
    return PipelineState(
        user_id=str(user.id),
        session_id=str(session.id),
        user_message=req.message,
        history=session.history or [],
        free_tier_mode=req.free_tier_mode,
        aws_session=aws_session,
        provider=provider,
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
        if fail:
            # Deterministic honesty, independent of the LLM summary's narrative:
            # the model has been observed declaring success after executing only
            # part of a plan. The user must never learn the truth from the AWS bill.
            content += (
                f"\n\n⚠️ **{len(fail)} of {len(results)} steps did not complete.** "
                "Check the execution results below — the resources from failed steps do NOT exist."
            )
        if files:
            content += f"\n\n{len(files)} config file(s) generated. Use the download button to grab them."

        session.generated_files = files
        session.history = state.history
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
        session.history = state.history
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


@router.get("/chat/providers")
async def list_providers(request: Request, db: AsyncSession = Depends(get_db)):
    """Which of KNOWN_PROVIDERS this user can actually use right now — either
    the shared operator key or their own (Settings > API Keys). The frontend's
    model selector used to offer all three unconditionally, so picking one with
    no key anywhere failed deep inside a chat turn with a raw ValueError instead
    of steering the user away from it up front."""
    user = await get_or_create_user(db, request.state.user_id)
    settings = await get_user_settings(db, user.id)
    user_keys = (settings.provider_keys_enc if settings else None) or {}
    available = {name: operator_key_configured(name) or name in user_keys for name in KNOWN_PROVIDERS}
    return {"providers": available}


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    await _spend_turn_budget(user)
    aws_session = await get_user_boto3_session(db, user.id)
    session = await _load_session(db, user, req)
    state = await _build_state(db, user, session, req, aws_session)

    # The agents block on Bedrock/boto3 — run the whole turn in the dedicated
    # turn executor so it doesn't stall the event loop or the default thread pool.
    #
    # This must never let an exception propagate unhandled: doing so bypasses normal
    # response formation (confirmed — the exception reaches the client as a raw
    # connection failure, not a clean HTTP response), which the browser reports as
    # a generic "Failed to fetch" with no indication anything server-side broke.
    if _turn_slots.locked():
        raise HTTPException(status_code=503, detail=_AT_CAPACITY, headers={"Retry-After": "30"})
    try:
        async with _turn_slots:
            state = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(_turn_executor, run_turn, state),
                timeout=TURN_TIMEOUT_SECONDS,
            )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=_TURN_TIMED_OUT)
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


# Strong references to in-flight turn tasks — asyncio only keeps weak refs, so
# without this a client disconnect could let the GC collect a task mid-deploy.
_turn_tasks: set = set()


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Same turn as /chat, but streamed as Server-Sent Events: one `progress` event per
    agent as the LangGraph graph advances (live activity feed), then a `final` event
    carrying the full response payload.

    The turn itself (graph + persistence) runs in a background task with its OWN DB
    session; the SSE generator merely observes it through a queue. This matters: if the
    browser disconnects mid-deploy (tab close, refresh), Starlette cancels the response
    generator — but real AWS resources may already be provisioning. Structured this way,
    a disconnect kills the observer, never the turn, so the Deployment row / history /
    ui_messages are always written, exactly like the non-streaming /chat endpoint.
    """
    user = await get_or_create_user(db, request.state.user_id)
    await _spend_turn_budget(user)
    aws_session = await get_user_boto3_session(db, user.id)
    session = await _load_session(db, user, req)
    state = await _build_state(db, user, session, req, aws_session)

    if _turn_slots.locked():
        raise HTTPException(status_code=503, detail=_AT_CAPACITY, headers={"Retry-After": "30"})

    clerk_user_id = request.state.user_id
    session_id = str(session.id)
    queue: asyncio.Queue = asyncio.Queue()

    async def run_and_finalize():
        loop = asyncio.get_running_loop()
        holder: dict = {}

        def produce():
            # stream_turn drives the graph synchronously (blocking Bedrock/boto3
            # calls); progress events hop back to the event loop via the queue.
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

        try:
            try:
                async with _turn_slots:
                    await asyncio.wait_for(
                        loop.run_in_executor(_turn_executor, produce),
                        timeout=TURN_TIMEOUT_SECONDS,
                    )
            except asyncio.TimeoutError:
                holder["error"] = _TURN_TIMED_OUT
                holder.pop("state", None)

            if "error" in holder:
                queue.put_nowait(
                    {"type": "error", "message": f"Sorry, something went wrong: {holder['error']}"}
                )
                return

            # Fresh DB session: the request-scoped one is torn down with the HTTP
            # response, which may already be gone if the client disconnected.
            async with async_session_local() as bg_db:
                bg_user = await get_or_create_user(bg_db, clerk_user_id)
                bg_session = await _get_owned_session(bg_db, bg_user.id, session_id)
                payload = await _finalize_turn(bg_db, bg_user, bg_session, holder["state"])
            queue.put_nowait({"type": "final", **payload})
        except Exception:
            queue.put_nowait(
                {"type": "error", "message": "Sorry, something went wrong saving your turn. Please try again."}
            )
        finally:
            queue.put_nowait(None)  # done sentinel

    task = asyncio.create_task(run_and_finalize())
    _turn_tasks.add(task)
    task.add_done_callback(_turn_tasks.discard)

    async def sse():
        while True:
            # Heartbeat comments while the graph is quiet (a single agent stage can
            # run for minutes with no progress event) — without them, proxies and
            # load balancers with idle timeouts kill the connection mid-deploy.
            # SSE comment lines (leading ":") are ignored by the client parser.
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if event is None:
                break
            yield _sse(event)

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Tell nginx-family proxies not to buffer the stream — buffered SSE
            # arrives all at once at the end, which defeats the entire feature.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/files/{session_id}")
async def get_files(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    session = await _get_owned_session(db, user.id, session_id)
    if not session or not session.generated_files:
        return {"files": {}}
    return {"files": session.generated_files}
