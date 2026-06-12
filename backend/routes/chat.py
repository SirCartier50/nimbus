import uuid
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agents.architect import run_architect
from agents.executor import run_executor
from agents.file_generator import generate_files
from routes.workspace import _get_or_create_workspace

router = APIRouter()

_sessions: dict = {}
_MAX_SESSIONS = 500


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=4000)
    session_id: Optional[str] = None
    confirm: Optional[bool] = None
    free_tier_mode: Optional[bool] = True


class ChatResponse(BaseModel):
    session_id: str
    role: str
    content: str
    awaiting_confirmation: bool = False
    plan: Optional[dict] = None
    execution_results: Optional[list] = None
    generated_files: Optional[dict] = None


DESTRUCTIVE_ACTIONS = {"stop_ec2", "terminate_ec2", "delete_s3", "delete_dynamodb", "delete_lambda"}


def _plan_is_destructive(plan: dict) -> bool:
    for step in plan.get("plan", []):
        action = step.get("action", "")
        if any(d in action for d in ("stop", "terminate", "delete")):
            return True
    return False


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    if session_id not in _sessions:
        # Evict oldest session if at capacity
        if len(_sessions) >= _MAX_SESSIONS:
            oldest = next(iter(_sessions))
            del _sessions[oldest]
        _sessions[session_id] = {
            "history": [],
            "pending_plan": None,
            "plan_is_destructive": False,
        }

    session = _sessions[session_id]

    # --- Handle confirmation of a pending plan ---
    if req.confirm is not None and session["pending_plan"]:
        if not req.confirm:
            session["pending_plan"] = None
            session["plan_is_destructive"] = False
            return ChatResponse(
                session_id=session_id,
                role="assistant",
                content="Plan cancelled. Nothing was deployed. Ask me to build something else!",
            )

        plan = session.pop("pending_plan")
        is_destructive = session.pop("plan_is_destructive", False)

        # Run the executor AI agent
        exec_result = run_executor(
            plan,
            free_tier_mode=req.free_tier_mode,
            allow_destructive=is_destructive,
        )

        results = exec_result["results"]
        ok = [r for r in results if r.get("success")]
        fail = [r for r in results if not r.get("success")]

        files = generate_files(plan, results)

        if files:
            ws = _get_or_create_workspace()
            for filename, content in files.items():
                with open(os.path.join(ws, filename), "w") as f:
                    f.write(content)

        # Use the executor AI's summary as the primary content
        content = exec_result["text"]

        # Append file info if generated
        if files:
            content += f"\n\n{len(files)} config file(s) generated. Use the download button to grab them."

        return ChatResponse(
            session_id=session_id,
            role="assistant",
            content=content,
            execution_results=results,
            generated_files=files,
        )

    # --- Normal message: send to architect agent ---
    result = run_architect(
        req.message,
        session["history"],
        free_tier_mode=req.free_tier_mode,
    )

    if not result["success"]:
        return ChatResponse(
            session_id=session_id,
            role="assistant",
            content=f"Sorry, I had trouble with that: {result.get('text', 'Unknown error')}. Please try again.",
        )

    # Update conversation history
    session["history"] = result["messages"]

    # If the architect produced a plan, ask for confirmation
    if result["plan"]:
        plan = result["plan"]
        session["pending_plan"] = plan
        session["plan_is_destructive"] = _plan_is_destructive(plan)

        content = result["text"]

        # Add plan details
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

        if session["plan_is_destructive"]:
            content += "\n\n🚨 **This plan includes destructive actions that cannot be undone.**"

        content += "\n\nShall I go ahead? Reply **yes** to deploy or **no** to cancel."

        return ChatResponse(
            session_id=session_id,
            role="assistant",
            content=content,
            awaiting_confirmation=True,
            plan=plan,
        )

    # No plan — conversational response (the architect answered directly)
    return ChatResponse(
        session_id=session_id,
        role="assistant",
        content=result["text"],
    )


@router.get("/files/{session_id}")
async def get_files(session_id: str):
    session = _sessions.get(session_id)
    if not session or not session.get("generated_files"):
        return {"files": {}}
    return {"files": session["generated_files"]}
