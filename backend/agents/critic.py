"""Tier-2 plan critic (PIPELINE_PLAN.md §3).

A single LLM pass that reviews a proposed plan against the user's requirements and
reports problems — it does NOT rewrite the plan and it does NOT loop. Its findings are
surfaced to the user at the approval gate, where the user adjudicates the judgment
calls. Advisory only: if the model is unavailable or returns junk, it degrades to "no
findings" rather than blocking the pipeline.
"""
import json

from utils.llm import run_completion

CRITIC_PROMPT = """You are Nimbus Critic, a senior AWS reviewer. You review a proposed
infrastructure plan against the user's requirements and surface real problems —
security risks, cost surprises, missing pieces, over- or under-provisioning. You do
NOT rewrite the plan; you report.

Return ONLY a JSON object, no prose, in exactly this shape:
{"blocking_issues": ["..."], "suggestions": ["..."]}

- blocking_issues: problems serious enough that the plan should NOT be deployed as-is
  (e.g. a security group open to 0.0.0.0/0 on SSH, a resource that won't function
  because something it needs is missing). Use an empty list if there are none.
- suggestions: non-blocking improvements (a cheaper option, a best-practice nit).
  Use an empty list if there are none.

Be specific and concise — one short, beginner-friendly sentence per item. Do NOT invent
problems to seem useful: a clean plan with two empty lists is a perfectly good review."""


def run_critic(spec: dict, plan: dict, provider=None) -> dict:
    user = (
        f"User requirements:\n{json.dumps(spec, indent=2, default=str)}\n\n"
        f"Proposed plan:\n{json.dumps(plan, indent=2, default=str)}\n\n"
        "Review it."
    )
    try:
        data = _parse_json(run_completion(CRITIC_PROMPT, user, provider=provider))
        return {
            "blocking_issues": [str(x) for x in data.get("blocking_issues", []) if x],
            "suggestions": [str(x) for x in data.get("suggestions", []) if x],
        }
    except Exception:
        return {"blocking_issues": [], "suggestions": []}


def _parse_json(text: str) -> dict:
    """Tolerate code fences / surrounding prose by grabbing the outermost JSON object."""
    text = text.strip()
    start, end = text.index("{"), text.rindex("}")
    return json.loads(text[start:end + 1])
