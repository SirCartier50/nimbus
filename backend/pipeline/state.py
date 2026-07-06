"""The state object threaded through the agent pipeline.

Every agent is a `(PipelineState) -> PipelineState` node (see orchestrator.py).
This is deliberately the LangGraph node signature: if/when we adopt LangGraph
(see PIPELINE_PLAN.md §4), the nodes drop in unchanged and only the orchestration
shell is swapped.

Fields are grouped by who sets them: the route fills inputs/context each turn and
reads outputs back to persist + respond. Several fields are reserved for later
phases (Requirements, validation/critic) so the shape doesn't churn as agents land.
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PipelineState:
    # --- inputs / context (set by the route each turn) ---
    user_id: str
    session_id: str
    user_message: str = ""
    history: list = field(default_factory=list)
    free_tier_mode: bool = True
    aws_session: Any = None              # per-user boto3 Session
    provider: Optional[str] = None       # LLM provider override; None = env default

    # --- confirmation control (rehydrated from the DB session row by the route) ---
    confirm: Optional[bool] = None       # the user's yes/no to a pending plan
    pending_plan: Optional[dict] = None
    plan_is_destructive: bool = False

    # --- outputs (produced by nodes, read back by the route) ---
    outcome: str = "conversation"        # conversation | plan_proposed | executed | cancelled
    plan: Optional[dict] = None          # a plan freshly proposed this turn
    awaiting_confirmation: bool = False
    execution_results: Optional[list] = None
    generated_files: Optional[dict] = None
    health: Optional[list] = None        # post-deploy health checks (Validator)
    display_text: str = ""

    # --- requirements (front door) ---
    requirements_spec: Optional[dict] = None
    requirements_complete: bool = False

    # --- validation: Tier-1 (deterministic, loops) + Tier-2 critic (surfaced) ---
    validation_blocking: list = field(default_factory=list)
    validation_suggestions: list = field(default_factory=list)
    validation_rounds: int = 0
    # Snapshot of the previous round's blocking issues — the graph's validate→architect
    # cycle uses it to detect oscillation (same issues twice = stuck, stop refining).
    previous_validation_blocking: Optional[list] = None
    stage: str = "requirements"
