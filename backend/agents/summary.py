"""Summary agent (PIPELINE_PLAN.md §2, Summary).

After the Executor runs and the Validator checks health, this turns the raw results
into a warm, plain-English message for a beginner. Returns "" if the model is
unavailable, so the caller can fall back to the executor's own text.
"""
import json

from utils.llm import run_completion

SUMMARY_PROMPT = """You are Nimbus, telling a BEGINNER what just happened when their AWS
infrastructure was deployed. Be warm, clear, and jargon-free. Briefly cover:
- what was created (in plain terms) and its id
- anything that failed, and what that means for them
- any health check that didn't pass
- one friendly next step

Keep it short — a few sentences or bullets. Output just the message, no JSON."""


def run_summary(plan: dict, results: list, health: list, provider=None) -> str:
    payload = {"results": results, "health": health}
    user = f"Deployment results:\n{json.dumps(payload, indent=2, default=str)}\n\nWrite the summary."
    try:
        return run_completion(SUMMARY_PROMPT, user, provider=provider).strip()
    except Exception:
        return ""
