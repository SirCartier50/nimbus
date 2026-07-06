from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import get_or_create_user
from db.deps import get_db
from db.models import Session as SessionModel
from routes.chat import _get_owned_session

router = APIRouter()


class RenameSessionBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


@router.get("/sessions")
async def list_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Lightweight session summaries (title/id/timestamps only, never message
    bodies) for the sidebar. `limit`/`offset` let the frontend show the first 5
    then paginate in more on "Load more" rather than fetching everything upfront."""
    user = await get_or_create_user(db, request.state.user_id)

    total = (
        await db.execute(
            select(func.count()).select_from(SessionModel).where(SessionModel.user_id == user.id)
        )
    ).scalar_one()

    result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == user.id)
        .order_by(SessionModel.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    sessions = result.scalars().all()
    return {
        "sessions": [
            {
                "id": str(s.id),
                "title": s.title or "New conversation",
                "model": s.model,
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
            }
            for s in sessions
        ],
        "total": total,
        "has_more": offset + len(sessions) < total,
    }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db, request.state.user_id)
    session = await _get_owned_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "id": str(session.id),
        "title": session.title or "New conversation",
        "model": session.model,
        "messages": session.ui_messages or [],
        "pending_plan": session.pending_plan,
        "plan_is_destructive": session.plan_is_destructive,
    }


@router.patch("/sessions/{session_id}")
async def rename_session(
    session_id: str, body: RenameSessionBody, request: Request, db: AsyncSession = Depends(get_db)
):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    user = await get_or_create_user(db, request.state.user_id)
    session = await _get_owned_session(db, user.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    session.title = title
    await db.commit()
    return {"id": str(session.id), "title": session.title}
