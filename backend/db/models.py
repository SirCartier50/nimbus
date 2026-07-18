import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from db.engine import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clerk_user_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    settings: Mapped["UserSettings"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    deployments: Mapped[list["Deployment"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    # STS AssumeRole model: the user deploys a CloudFormation stack in their own
    # account that trusts Nimbus's service identity, scoped by a per-user external_id
    # (confused-deputy protection). Neither value is a secret — an ARN is an
    # identifier, and AWS's own guidance is that an external_id only needs to be
    # unique/random, not encrypted — so no Fernet encryption here (see utils/aws_role.py).
    aws_role_arn: Mapped[str | None] = mapped_column(String, nullable=True)
    aws_external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    github_repo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="settings")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False, server_default="us-east-1")
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # The frontend's rendered message shape (role, content, plan, execution_results,
    # generated_files, timestamp) — distinct from `history`, which is the raw
    # agent-loop conversation format the LLM providers consume. Needed so switching
    # to a past session in the UI can re-render it faithfully instead of just
    # resuming the underlying agent context blind.
    ui_messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    pending_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    plan_is_destructive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    generated_files: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now(), index=True)

    user: Mapped["User"] = relationship(back_populates="sessions")
    deployments: Mapped[list["Deployment"]] = relationship(back_populates="session")


# Bodyguard's user-facing output used to live only in process RAM, so every
# deploy/restart silently wiped a user's alert history. These three tables are
# the durable store; the patrol loop writes them after each cycle and the
# dashboard routes read them directly. They are also the handoff medium for
# extracting Bodyguard into its own worker process (the API only ever reads).
class BodyguardAlert(Base):
    __tablename__ = "bodyguard_alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False, server_default="warning")
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class BodyguardLog(Base):
    __tablename__ = "bodyguard_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    level: Mapped[str] = mapped_column(String, nullable=False, server_default="info")
    message: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class BodyguardStatus(Base):
    """One row per patrolled user: cycle bookkeeping + the latest sub-resource
    snapshot (volumes/EIPs/snapshots), which is a point-in-time view — only the
    newest one matters, so it's a column here rather than an append-only table."""

    __tablename__ = "bodyguard_status"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    last_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    instances_stopped: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sub_resources: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    plan: Mapped[dict] = mapped_column(JSONB, nullable=False)
    results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="deployments")
    session: Mapped["Session | None"] = relationship(back_populates="deployments")
