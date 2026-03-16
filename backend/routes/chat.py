import uuid
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from agents.architect import run_architect
from agents.executor import execute_plan
from agents.file_generator import generate_files
from routes.workspace import _get_or_create_workspace
import os

router = APIRouter()

_sessions: dict = {}


class ChatRequest(BaseModel):
    message: str
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


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())

    if session_id not in _sessions:
        _sessions[session_id] = {"history": [], "pending_plan": None}

    session = _sessions[session_id]

    if req.confirm is not None and session["pending_plan"]:
        if not req.confirm:
            session["pending_plan"] = None
            return ChatResponse(
                session_id=session_id,
                role="assistant",
                content="Plan cancelled. Nothing was deployed. Ask me to build something else!",
            )

        plan = session.pop("pending_plan")
        results = execute_plan(plan, free_tier_mode=req.free_tier_mode)

        ok = [r for r in results if r.get("success")]
        fail = [r for r in results if not r.get("success")]

        files = generate_files(plan, results)
        session["generated_files"] = files

        if files:
            ws = _get_or_create_workspace()
            for filename, content in files.items():
                with open(os.path.join(ws, filename), "w") as f:
                    f.write(content)

        lines = []
        for r in results:
            if r.get("success"):
                lines.append(f"✅ {r.get('message', r.get('description', ''))}")
            else:
                lines.append(f"❌ {r.get('description', '')}: {r.get('error', 'unknown error')}")

        content = (
            f"Deployment complete!\n\n"
            + "\n".join(lines)
            + f"\n\n{len(ok)} succeeded, {len(fail)} failed."
        )
        if files:
            content += f"\n\n{len(files)} config file(s) generated. Use the download button to grab them."
        if fail:
            content += "\n\nCheck the dashboard for details."

        return ChatResponse(
            session_id=session_id,
            role="assistant",
            content=content,
            execution_results=results,
            generated_files=files,
        )

    result = run_architect(req.message, session["history"], free_tier_mode=req.free_tier_mode)

    if not result["success"]:
        return ChatResponse(
            session_id=session_id,
            role="assistant",
            content=f"Sorry, I couldn't plan that: {result['error']}. Please try rephrasing.",
        )

    plan = result["plan"]
    session["pending_plan"] = plan

    session["history"].append({"role": "user", "content": [{"text": req.message}]})
    session["history"].append({"role": "assistant", "content": [{"text": result["raw"]}]})

    steps_text = "\n".join(
        f"  {i + 1}. {s.get('description', s.get('action', ''))}"
        for i, s in enumerate(plan.get("plan", []))
    )
    cost_note = plan.get("cost_warning", "")
    estimated = plan.get("estimated_monthly_cost", "$0.00 (free tier)")

    content = (
        f"{plan.get('explanation', 'Here is what I will build:')}\n\n"
        f"**Plan:**\n{steps_text}\n\n"
        f"**Estimated monthly cost:** {estimated}"
    )
    if cost_note:
        content += f"\n\n⚠️  {cost_note}"
    content += "\n\nShall I go ahead? Reply **yes** to deploy or **no** to cancel."

    return ChatResponse(
        session_id=session_id,
        role="assistant",
        content=content,
        awaiting_confirmation=True,
        plan=plan,
    )


@router.get("/files/{session_id}")
async def get_files(session_id: str):
    session = _sessions.get(session_id)
    if not session or not session.get("generated_files"):
        return {"files": {}}
    return {"files": session["generated_files"]}
