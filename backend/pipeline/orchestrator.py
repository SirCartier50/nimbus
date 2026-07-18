"""Pipeline orchestration — a LangGraph StateGraph.

The control flow that used to be hand-rolled `if/return` routing in `run_turn` is now
a real graph: nodes are the agents, edges are the routing, and the Tier-1 validation
refinement is a genuine graph **cycle** (validate → architect → validate) rather than a
`while` loop. Every node is `(PipelineState) -> dict-of-updates`; LangGraph merges the
updates into the state and follows the edges.

Scope of the graph = ONE turn. A turn runs to a natural stopping point and returns to
the web route (`routes/chat.py`), which owns cross-request persistence (saving the
pending plan / history to Postgres) and the HTTP response. The two human-in-the-loop
pauses — mid-intake and the approval gate — are simply the graph reaching END with an
`outcome` of "conversation" / "plan_proposed"; the next HTTP request starts a fresh
`invoke`. (A LangGraph checkpointer could later own that persistence too — see
PIPELINE_PLAN.md §4 — but the graph structure and the intra-turn cycle don't need it.)

The map:

    START ─▶ (route_entry) ─┬─▶ requirements ─▶ (done?) ─┬─▶ architect ─▶ (plan?) ─┬─▶ validate
                            │                             └─▶ END                  └─▶ END
                            ├─▶ executor ─▶ END                                          │
                            └─▶ cancel ─▶ END                    ┌───── (refine?) ───────┤
                                                                 ▼                        ▼
                                                            architect ◀───────────── (issues)
                                                                                          │
                                                                                    (clean/stuck)
                                                                                          ▼
                                                                                      finalize ─▶ END
"""
from langgraph.graph import END, START, StateGraph

from agents.architect import run_architect
from agents.critic import run_critic
from agents.executor import run_executor
from agents.file_generator import generate_files
from agents.requirements import build_spec_handoff, run_requirements
from agents.summary import run_summary
from pipeline.cost import estimate_plan_cost
from pipeline.state import PipelineState
from pipeline.validation import validate_plan
from pipeline.validator import run_validator

# Backstop for the validate→architect cycle. The primary stop is convergence (issues
# stop changing); this just guarantees termination. See PIPELINE_PLAN.md §3.
MAX_VALIDATION_ROUNDS = 4


def plan_is_destructive(plan: dict) -> bool:
    for step in plan.get("plan", []):
        if any(d in step.get("action", "") for d in ("stop", "terminate", "delete")):
            return True
    return False


# ---------------------------------------------------------------------------
# Nodes — each returns a dict of state fields to update
# ---------------------------------------------------------------------------


def requirements_node(state: PipelineState) -> dict:
    """Front door: answer a question/lookup, or gather requirements. Sets
    requirements_complete (+ spec) when intake finishes this turn."""
    result = run_requirements(
        state.user_message, state.history,
        free_tier_mode=state.free_tier_mode, aws_session=state.aws_session, provider=state.provider,
    )
    updates = {"history": result["messages"]}
    if result.get("spec") is not None:
        updates["requirements_spec"] = result["spec"]
        updates["requirements_complete"] = True
    else:
        updates["display_text"] = result["text"]
        updates["outcome"] = "conversation"
    return updates


def architect_node(state: PipelineState) -> dict:
    """Propose a plan. Two modes: initial (turn the spec into a plan) or refine (fix
    the blocking issues Tier-1 validation just found). It's the same node either way —
    the cycle re-enters it — distinguished by whether there are blocking issues."""
    if state.validation_blocking:  # refine mode (came back around the cycle)
        feedback = (
            "The proposed plan has these problems:\n- "
            + "\n- ".join(state.validation_blocking)
            + "\n\nProduce a corrected plan that fixes them."
        )
        result = run_architect(
            feedback, state.history,
            free_tier_mode=state.free_tier_mode, aws_session=state.aws_session, provider=state.provider,
        )
        updates = {
            "history": result["messages"],
            "validation_rounds": state.validation_rounds + 1,
            "previous_validation_blocking": state.validation_blocking,
        }
        # If the architect stops producing a plan, keep the last good one (don't
        # overwrite state.plan); validation will re-run and converge via the backstop.
        if result.get("plan"):
            updates.update({
                "plan": result["plan"], "pending_plan": result["plan"],
                "display_text": result["text"],
                "plan_is_destructive": plan_is_destructive(result["plan"]),
            })
        return updates

    # initial mode
    user_request = (
        build_spec_handoff(state.requirements_spec)
        if state.requirements_spec is not None else state.user_message
    )
    result = run_architect(
        user_request, state.history,
        free_tier_mode=state.free_tier_mode, aws_session=state.aws_session, provider=state.provider,
    )
    updates = {"history": result["messages"], "display_text": result["text"]}
    if result.get("plan"):
        updates.update({
            "plan": result["plan"], "pending_plan": result["plan"],
            "plan_is_destructive": plan_is_destructive(result["plan"]),
            "awaiting_confirmation": True, "outcome": "plan_proposed",
        })
    else:
        updates["outcome"] = "conversation"
    return updates


def validate_node(state: PipelineState) -> dict:
    """Tier-1 deterministic checks. Just records the blocking issues; the edge out of
    this node (route_after_validate) decides whether to refine or finalize."""
    return {"validation_blocking": validate_plan(state.plan, state.free_tier_mode)}


def finalize_node(state: PipelineState) -> dict:
    """Attach the real cost estimate and run the single Tier-2 critic pass. The critic's
    findings are surfaced to the user at the gate — they never re-enter the cycle."""
    plan = dict(state.plan)
    cost = estimate_plan_cost(plan, state.free_tier_mode, aws_session=state.aws_session)
    plan["estimated_monthly_cost"] = cost["formatted"]
    plan["cost_breakdown"] = cost["breakdown"]

    critique = run_critic(state.requirements_spec, plan, provider=state.provider)
    return {
        "plan": plan,
        "pending_plan": plan,
        "validation_blocking": state.validation_blocking + critique["blocking_issues"],
        "validation_suggestions": critique["suggestions"],
    }


def _reconcile_results(plan: dict, results: list) -> list:
    """The executor is an LLM agent — a weak model can stop after executing only
    some of the plan's steps while sounding finished (observed live: 1 of 3 steps
    executed, status still 'success'). Code, not the model, is accountable for
    completeness: any plan step beyond what the agent actually executed becomes an
    explicit failure entry, so status/summary/UI all reflect the truth."""
    steps = plan.get("plan", []) if isinstance(plan, dict) else []
    missing = len(steps) - len(results)
    if missing <= 0:
        return results
    reconciled = list(results)
    for step in steps[len(results):]:
        reconciled.append({
            "success": False,
            "action": step.get("action"),
            "resource_type": step.get("resource_type"),
            "name": step.get("description", "")[:80] or step.get("resource_type", "step"),
            "error": "This step was never executed by the agent — the deployment is incomplete.",
        })
    return reconciled


def _execution_history_note(results: list) -> str:
    """Compact, factual record of the executed turn for the agent-visible history.
    Without this, post-deploy turns saw a conversation frozen at 'plan proposed'
    and re-asked the user whether they were ready to deploy."""
    lines = []
    for r in results:
        label = r.get("resource_type") or r.get("action") or "step"
        if r.get("success"):
            lines.append(f"- {label}: created/completed successfully")
        else:
            lines.append(f"- {label}: FAILED — {str(r.get('error', 'unknown error'))[:120]}")
    return "The user confirmed the plan and it was executed. Results:\n" + "\n".join(lines)


def executor_node(state: PipelineState) -> dict:
    plan = state.pending_plan
    result = run_executor(
        plan, free_tier_mode=state.free_tier_mode, allow_destructive=state.plan_is_destructive,
        aws_session=state.aws_session, provider=state.provider,
        use_cloud_control=True,   # generic breadth: any "AWS::..." type via Cloud Control
    )
    results = _reconcile_results(plan, result["results"])
    health = run_validator(results, state.aws_session)
    summary = run_summary(plan, results, health, provider=state.provider)
    return {
        "execution_results": results,
        "generated_files": generate_files(plan, results) or {},
        "plan": plan,                       # keep the executed plan for the deployment record
        "health": health,
        "display_text": summary or result["text"],
        # Record the executed turn in the agent-visible history so follow-up
        # turns know the deployment already happened.
        "history": state.history + [
            {"role": "user", "content": [{"text": "Yes — deploy the proposed plan."}]},
            {"role": "assistant", "content": [{"text": _execution_history_note(results)}]},
        ],
        "pending_plan": None,               # clear the gate
        "plan_is_destructive": False,
        "awaiting_confirmation": False,
        "outcome": "executed",
    }


def cancel_node(state: PipelineState) -> dict:
    return {
        "pending_plan": None,
        "plan_is_destructive": False,
        "display_text": "Plan cancelled. Nothing was deployed. Ask me to build something else!",
        "history": state.history + [
            {"role": "user", "content": [{"text": "No — do not deploy the plan."}]},
            {"role": "assistant", "content": [{"text": "Understood — the plan was cancelled and nothing was deployed."}]},
        ],
        "outcome": "cancelled",
    }


# ---------------------------------------------------------------------------
# Edges — routing functions return the name of the next node
# ---------------------------------------------------------------------------


def route_entry(state: PipelineState) -> str:
    # Confirming (or rejecting) a previously proposed plan short-circuits the pipeline.
    if state.confirm is not None and state.pending_plan:
        return "executor" if state.confirm else "cancel"
    return "requirements"


def route_after_requirements(state: PipelineState) -> str:
    return "architect" if state.requirements_complete else END


def route_after_architect(state: PipelineState) -> str:
    return "validate" if state.outcome == "plan_proposed" else END


def route_after_validate(state: PipelineState) -> str:
    """The Tier-1 cycle's decision. Refine (loop back to architect) only while there
    are blocking issues AND they're still changing AND we're under the backstop."""
    issues = state.validation_blocking
    if not issues:
        return "finalize"
    if issues == state.previous_validation_blocking:   # oscillation — not improving
        return "finalize"
    if state.validation_rounds >= MAX_VALIDATION_ROUNDS:
        return "finalize"
    return "architect"


# ---------------------------------------------------------------------------
# Graph assembly (compiled once at import)
# ---------------------------------------------------------------------------


def _build_graph():
    g = StateGraph(PipelineState)
    g.add_node("requirements", requirements_node)
    g.add_node("architect", architect_node)
    g.add_node("validate", validate_node)
    g.add_node("finalize", finalize_node)
    g.add_node("executor", executor_node)
    g.add_node("cancel", cancel_node)

    g.add_conditional_edges(START, route_entry,
                            {"requirements": "requirements", "executor": "executor", "cancel": "cancel"})
    g.add_conditional_edges("requirements", route_after_requirements, {"architect": "architect", END: END})
    g.add_conditional_edges("architect", route_after_architect, {"validate": "validate", END: END})
    g.add_conditional_edges("validate", route_after_validate, {"architect": "architect", "finalize": "finalize"})
    g.add_edge("finalize", END)
    g.add_edge("executor", END)
    g.add_edge("cancel", END)
    return g.compile()


_GRAPH = _build_graph()

_STATE_FIELDS = set(PipelineState.__dataclass_fields__)


def _rebuild(fields: dict) -> PipelineState:
    return PipelineState(**{k: v for k, v in fields.items() if k in _STATE_FIELDS})


def run_turn(state: PipelineState) -> PipelineState:
    """Run one turn through the graph. LangGraph's invoke returns a plain dict of the
    final channel values; rebuild a PipelineState so the web route keeps attribute
    access (state.outcome, ...)."""
    result = _GRAPH.invoke(state)
    if isinstance(result, PipelineState):
        return result
    return _rebuild(result)


# Human-friendly label for each node, surfaced live as the graph runs so the UI can
# show which agent is working (the "activity feed"). A node can fire more than once —
# e.g. `architect` reappears each time the Tier-1 cycle sends a plan back to be fixed —
# which is exactly the progress we want the user to see.
STAGE_MESSAGES = {
    "requirements": "Understanding what you need…",
    "architect": "Designing your infrastructure plan…",
    "validate": "Checking the plan for problems…",
    "finalize": "Estimating cost and reviewing the plan…",
    "executor": "Deploying your resources…",
    "cancel": "Cancelling the plan…",
}


def stream_turn(state: PipelineState):
    """Run one turn, yielding a progress event as each graph node finishes, then a
    final event carrying the rebuilt PipelineState.

    Uses LangGraph's native `stream(stream_mode="updates")`, which emits one
    `{node_name: state_update}` chunk per node as the graph advances — so the caller
    gets live, per-agent progress instead of a single blocking wait. The terminal
    state is reconstructed by layering every node's update over the starting state
    (later updates win), the same fields `run_turn` would have returned.
    """
    accumulated = dict(_STATE_INIT(state))
    for chunk in _GRAPH.stream(state, stream_mode="updates"):
        for node, update in chunk.items():
            if isinstance(update, dict):
                accumulated.update(update)
            yield {"type": "progress", "stage": node, "message": STAGE_MESSAGES.get(node, f"Running {node}…")}
    yield {"type": "final", "state": _rebuild(accumulated)}


def _STATE_INIT(state: PipelineState) -> dict:
    # Shallow field snapshot of the starting state (dataclasses.asdict would deep-copy
    # and choke on the boto3 session held in aws_session).
    return {f: getattr(state, f) for f in _STATE_FIELDS}
