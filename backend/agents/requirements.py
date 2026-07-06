import json

from agents.inspection import INSPECTION_TOOL_CONFIG, build_handlers
from utils.tool_use import run_tool_loop



SPEC_FIELDS = [
    "intent",          # what they want to build, in plain terms
    "scale",           # expected traffic / number of users
    "budget_priority", # "cost", "performance", or "balanced"
    "region",          # AWS region preference
    "runtime",         # language/runtime if relevant, else null
    "database",        # database needs, else null
    "storage",         # storage needs, else null
    "compliance",      # compliance requirements, else "none"
]

BASE_PROMPT = """You are Nimbus Requirements, the first agent a user talks to. You help
non-technical people figure out exactly what AWS infrastructure they need, then hand a
clean specification to the Architect to plan. Your audience is BEGINNERS — never use
jargon without explaining it.

You operate in two modes. Decide which the user needs from their message:

## MODE A: Answer (questions, lookups, status)
If the user is asking a question or wants to see something — "what is Lambda?",
"show my S3 buckets", "how many EC2 instances do I have?", "am I on free tier?" —
just answer it. Use your tools to look up live data when needed. Do NOT start intake
and do NOT emit a specification. Keep answering follow-ups until they want to build.

## MODE B: Gather requirements (the user wants to BUILD / change infrastructure)
Run a THOROUGH intake. Ask ONE question at a time. With every question:
- give 2-4 concrete options and explain the tradeoff of each in plain English
- recommend a sensible default and say why
- if the user doesn't know or says "you decide", accept your recommended default and move on

Collect ALL of these before finishing:
- intent: what they're building (e.g. "a website", "an API backend", "a place to store files")
- scale: how much traffic / how many users they expect
- budget_priority: do they care most about low cost, best performance, or a balance?
- region: which AWS region (recommend one near their users if they don't know)
- runtime: programming language / runtime, if they're deploying code (else not applicable)
- database: do they need a database, and what kind
- storage: do they need file/object storage
- compliance: any compliance needs (HIPAA, GDPR, etc.), or none

Ask about related items together when natural, but never dump the whole list at once —
one focused question per turn. Confirm anything ambiguous.

When — and only when — you have enough to fully specify the build, output a short
confirmation sentence to the user, then on its OWN line emit the finalized spec wrapped
in tags exactly like this:

<requirements-complete>
{{"intent": "...", "scale": "...", "budget_priority": "...", "region": "...", "runtime": null, "database": null, "storage": null, "compliance": "none"}}
</requirements-complete>

Rules for the spec:
- Use null for fields that genuinely don't apply (e.g. runtime for a static file bucket).
- Only emit the tag once you are gathering a NEW build. If earlier in the conversation a
  build was already specified and the user now wants something different or additional,
  gather the new/changed details first, then emit an updated spec.
- Never emit the tag in MODE A.

{free_tier_clause}
"""

FREE_TIER_CLAUSE = """STRICT FREE-TIER MODE IS ON. Steer the user toward free-tier-eligible
choices (e.g. a t2.micro/t3.micro server, no NAT gateway / RDS / load balancer). If what
they want can't fit free tier, say so plainly and offer the closest free option."""

FLEXIBLE_CLAUSE = """Free-tier mode is OFF. Any service is on the table, but still be
transparent about cost and prefer cost-effective options unless they prioritize performance."""


def _build_system_prompt(free_tier_mode: bool = True) -> str:
    clause = FREE_TIER_CLAUSE if free_tier_mode else FLEXIBLE_CLAUSE
    return BASE_PROMPT.format(free_tier_clause=clause)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_requirements(
    user_request: str,
    conversation_history: list = None,
    free_tier_mode: bool = True,
    aws_session=None,
    provider=None,
) -> dict:
    """Returns {"text", "spec", "messages"}. `spec` is a dict when intake just
    completed this turn, else None (still gathering, or answering a question)."""
    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": [{"text": user_request}]})

    result = run_tool_loop(
        system_prompt=_build_system_prompt(free_tier_mode),
        messages=messages,
        tool_config=INSPECTION_TOOL_CONFIG,
        tool_handlers=build_handlers(aws_session),
        provider=provider,
    )

    display_text, spec = extract_spec(result["text"])
    out_messages = result["messages"]
    if spec is not None:
        # Keep the control tag out of the persisted conversation so a later turn's
        # intake doesn't trip over a stale completion signal.
        out_messages = _scrub_last_assistant_text(out_messages, display_text)

    return {"text": display_text, "spec": spec, "messages": out_messages}


def build_spec_handoff(spec: dict) -> str:
    """The message the Architect receives once intake is done."""
    return (
        "The requirements gathering is complete. Here is the finalized specification:\n\n"
        f"{json.dumps(spec, indent=2)}\n\n"
        "Produce the deployment plan now."
    )


def extract_spec(text: str) -> tuple[str, dict | None]:
    """Pull the JSON spec out of a <requirements-complete> block and strip the tags
    from what the user sees. Returns (text, None) if there's no block, or the block
    is malformed JSON."""
    if "<requirements-complete>" not in text or "</requirements-complete>" not in text:
        return text, None

    start_idx = text.index("<requirements-complete>")
    end_idx = text.index("</requirements-complete>") + len("</requirements-complete>")

    try:
        start = start_idx + len("<requirements-complete>")
        end = text.index("</requirements-complete>")
        spec = json.loads(text[start:end].strip())

        display_text = text[:start_idx].strip()
        tail = text[end + len("</requirements-complete>"):].strip()
        if tail:
            display_text = (display_text + "\n" + tail).strip()
        return display_text, spec
    except (json.JSONDecodeError, ValueError):
        # The model attempted the completion protocol but the JSON inside was
        # malformed — a real failure mode for less capable/less instruction-
        # following models (more likely on non-Bedrock providers). Never show the
        # raw control tags or broken JSON fragment to the user; strip that block
        # out and keep whatever clean text surrounds it, so this turn just reads
        # as an ordinary (if unhelpful) reply instead of visibly broken output.
        before = text[:start_idx].strip()
        after = text[end_idx:].strip()
        cleaned = "\n".join(p for p in (before, after) if p)
        return cleaned or "Sorry, I had trouble with that — could you rephrase what you're looking to build?", None


def _scrub_last_assistant_text(messages: list, clean_text: str) -> list:
    """Replace the final assistant message's text with the tag-stripped version.
    The completion tag is a control signal, not conversation — it shouldn't linger
    in history. The terminal message is plain text (no toolUse blocks)."""
    if not messages or messages[-1].get("role") != "assistant":
        return messages
    messages = list(messages)
    messages[-1] = {"role": "assistant", "content": [{"text": clean_text}]}
    return messages
