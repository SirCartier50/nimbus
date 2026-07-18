# Nimbus AI — Agent Pipeline Plan

> Authoritative design for the multi-agent pipeline. (Supersedes the old
> `context.md`, now deleted — its "Executor = plain code", "6 generic tools", and
> "no critic loop" decisions never reflected the intended design.) Read alongside
> `DECISIONS.md` (cross-machine continuity) for current build status.
>
> Status of this doc: design agreed in the 2026-06-27 design session. Not yet
> implemented — this is the build plan.

---

## 1. The vision, restated correctly

Nimbus is a **multi-agent** system. The agents are the point — we are not
collapsing them into plain code. A user describes infrastructure in plain
English; a chain of specialized agents gathers requirements, designs a plan,
critiques it, gets human sign-off, deploys, verifies, and summarizes.

The generator–critic ("is this plan actually good?") loop is a real, intended
cycle — not a linear pipeline. The design below makes that loop **terminate
reliably** and **survive weak/free LLM providers**, which are the two things
that otherwise break a naive LLM-vs-LLM loop.

---

## 2. The pipeline

```
User message
     │
     ▼
┌─────────────────────┐
│ Requirements Agent  │  LLM. Conversational intake, one question at a time
│  (intent ground     │  with options/tradeoffs. Builds a structured spec.
│   truth = USER)     │  Emits spec when complete. ── HUMAN IN LOOP ──
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Architect Agent     │  LLM. spec → ordered JSON plan with real AWS configs
└─────────┬───────────┘  (botocore field names, the DEV-4 registry).
          ▼
┌─────────────────────┐
│ Tier-1 Validation   │  PLAIN CODE. Deterministic checks: schema valid,
│  (correctness loop) │  dependency graph acyclic, free-tier honored,
│                     │  required fields present. Loops back to Architect
│                     │  on failure. Safe to loop — code can't hallucinate
│   ◄──── loop ────►  │  false positives. Terminates on convergence.
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Tier-2 Critic       │  LLM. ONE pass. Judgment calls (over-provisioned?
│  (judgment, no loop)│  SG too open? cheaper option?). Produces a REPORT:
│                     │  {blocking_issues[], suggestions[]}. Does NOT loop
│                     │  silently with the Architect.
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ User gate           │  HUMAN IN LOOP. Show plan + critic report + REAL
│  (intent ground     │  cost estimate. User: deploy / revise / cancel.
│   truth = USER)     │  A "revise" is new Requirements input, NOT a silent
└─────────┬───────────┘  re-run of the critic loop.
          ▼ (deploy)
┌─────────────────────┐
│ Executor Agent      │  LLM. Runs the plan via the DEV-4 botocore tools.
└─────────┬───────────┘  (Intended as an agent — confirmed.)
          ▼
┌─────────────────────┐
│ Validator Agent     │  PLAIN CODE. Post-deploy: confirm resources are
│                     │  actually healthy (not just a 200 from boto3).
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Summary Agent       │  LLM. Plain-English result for a beginner.
└─────────────────────┘

Bodyguard runs separately as a background daemon. Out of scope for this plan —
leave as-is (per 2026-06-27 decision).
```

### Agent inventory vs. status

| Agent | Type | Status |
|---|---|---|
| Requirements | LLM | ✅ Built (`agents/requirements.py`) — thorough intake + Q&A triage front door |
| Architect | LLM | ✅ Plan-only (`agents/architect.py`); conversational mode removed; inspection tools shared via `agents/inspection.py` |
| Tier-1 Validation | Plain code | ✅ Built (`pipeline/validation.py`) — deterministic, loops back to Architect |
| Tier-2 Critic | LLM | ✅ Built (`agents/critic.py`) — single pass, surfaced to user, never loops |
| Cost estimate | Plain code | ✅ Built (`pipeline/cost.py` + `pipeline/pricing_api.py`) — live AWS Pricing API w/ static-table fallback; replaces guessed cost |
| Executor | LLM | ✅ Node (`pipeline/orchestrator.executor_node`); now also health-validates + summarizes |
| Validator | Plain code | ✅ Built (`pipeline/validator.py`) — post-deploy health checks, never raises |
| Summary | LLM | ✅ Built (`agents/summary.py`) — final plain-English message; falls back to executor text |
| Bodyguard | LLM daemon | Exists — leave as-is |

---

## 3. The critic loop — how it terminates without false-positive runaway

The naive failure mode: two LLMs ping-pong forever, the critic manufacturing
objections to seem useful. Three rules prevent that:

1. **Split correctness from judgment.**
   - **Tier-1 (deterministic, code):** schema validation (already have it),
     dependency-cycle check, free-tier rule check, required-field check. Code
     can't hallucinate, so this tier is *safe to loop* back to the Architect.
   - **Tier-2 (LLM critic):** only the fuzzy judgment calls. Runs **once** and
     produces a report — it does not gate an automatic loop.

2. **Terminate on convergence, not on a round count.** A fixed cap ("stop at 3")
   is wrong — round 4 might be better. Instead, the Tier-1 loop stops when the
   set of blocking issues *stops changing* between rounds (oscillation = stuck =
   stop). A hard ceiling (e.g. 8) exists only as a backstop against pathological
   loops, never as the primary stop.

3. **Severity-gate.** Validation output is `{blocking_issues[], suggestions[]}`.
   Only `blocking_issues` trigger a re-loop. `suggestions` are shown to the user
   but never loop. This is what prevents cosmetic nitpicks from looping forever.

**Where the human fits:** the user is the ground truth for *intent*, so they're
consulted at the two points where intent matters — Requirements (in) and the
plan gate (out). The Tier-2 critic's findings are surfaced *to the user* at the
gate ("reviewer flagged: NAT gateway ~$32/mo; SG open on port 22 — revise or
deploy?"). The user adjudicates the judgment calls. This is robust even when the
user picked a weak free model, because the objective gating already happened in
Tier-1 code.

The "what if round 4 was perfect" problem dissolves: only deterministic checks
auto-loop (and they converge definitively), while subjective refinement is
**unbounded but user-driven** — the human decides when it's good enough.

---

## 4. Orchestration — now a LangGraph StateGraph ✅ (2026-07-01)

**UPDATE: the orchestrator is now an actual LangGraph `StateGraph`** (`langgraph` 1.x,
`pipeline/orchestrator.py`). The earlier "plain orchestrator first" decision paid off
exactly as intended: because every agent was already a node-shaped function over
`PipelineState`, the migration only rewrote the ~30-line control shell — no agent, no
prompt, no test-of-an-agent changed.

What's a real graph now (verified by inspecting the compiled edges):
- **Nodes:** requirements, architect, validate, finalize, executor, cancel.
- **Conditional edges** replace the hand-rolled `if/return` routing (entry routing,
  requirements-done?, plan-proposed?).
- **A real cycle:** `validate → architect → validate` — the Tier-1 refinement is now an
  actual graph loop with a convergence-based conditional edge (`route_after_validate`),
  not a `while` loop buried in a node. Stops on clean / oscillation / `MAX_VALIDATION_ROUNDS`.
- `run_turn(state)` compiles-once then `invoke`s the graph and rebuilds a `PipelineState`
  from the returned dict (LangGraph `.invoke()` returns a plain dict).

**Scope = one turn.** The graph runs a turn and returns to `routes/chat.py`, which still
owns cross-request persistence (pending plan / history in Postgres). The two
human-in-the-loop pauses are just the graph hitting END with `outcome` =
"conversation"/"plan_proposed"; the next request is a fresh `invoke`.

**Live streaming — DONE (2026-07-01).** `pipeline/orchestrator.stream_turn()` drives the
graph with `stream(stream_mode="updates")` and yields one progress event per node as each
agent finishes (the refine cycle surfaces `architect` twice — visible progress), then a
final event with the rebuilt state. Exposed as SSE at `POST /api/chat/stream` (`chat.py`;
the sync graph stream is bridged to the async SSE response via a thread+queue, and both
`/chat` and `/chat/stream` share `_finalize_turn` so they persist/respond identically).
This is the "activity feed" / live-agent-reasoning feature. Unit-tested in
`test_orchestrator.py` (progress order, refine-cycle visibility, conversation/executor
paths); integration-tested in `test_chat_endpoint.py`.

**Still not adopted: the LangGraph checkpointer + `interrupt()`.** That would let LangGraph
*own* the pause/resume persistence (replacing the Postgres `pending_plan` rehydrate). It's
the remaining increment — see "When to adopt the checkpointer" below. The intra-turn cycle,
graph structure, and streaming deliberately don't need it. (It also requires moving
`aws_session`/`provider` out of the checkpointed state into runtime `config`, since a
boto3 Session isn't serializable — noted for whoever does it.)

---

*(Historical note — the original decision, kept for context:)* build a plain orchestrator
first but design every agent as a pure `(state) -> state` function — the LangGraph node
signature — so migration is a mechanical swap of the shell, not a rewrite. That's exactly
what happened.

### Shared state

```python
# backend/pipeline/state.py
@dataclass
class PipelineState:
    # context / identity
    user_id: str
    session_id: str
    aws_session: object          # per-user boto3 session (already exists)
    free_tier_mode: bool
    provider: str                # selected LLM provider/model id

    # conversation
    user_message: str
    history: list

    # requirements
    requirements_spec: dict | None = None
    requirements_complete: bool = False

    # plan + validation
    plan: dict | None = None
    validation_blocking: list = field(default_factory=list)
    validation_suggestions: list = field(default_factory=list)
    validation_rounds: int = 0

    # gating + execution
    awaiting_confirmation: bool = False
    execution_results: list | None = None

    # output + control
    display_text: str = ""
    stage: str = "requirements"  # current pipeline stage
```

### Node signature

```python
def requirements_node(state: PipelineState) -> PipelineState: ...
def architect_node(state: PipelineState)   -> PipelineState: ...
def tier1_validate(state: PipelineState)   -> PipelineState: ...  # plain code
def critic_node(state: PipelineState)      -> PipelineState: ...
def executor_node(state: PipelineState)    -> PipelineState: ...
def validator_node(state: PipelineState)   -> PipelineState: ...  # plain code
def summary_node(state: PipelineState)     -> PipelineState: ...
```

### Human-in-the-loop WITHOUT LangGraph

Generalize the pattern `chat.py` already uses for the confirm gate:

1. The orchestrator runs nodes until it reaches one that needs human input
   (Requirements not yet complete, or the plan gate).
2. It sets the relevant flag (`awaiting_confirmation` / `requirements_complete=False`),
   **persists `PipelineState` to the `sessions` row** (Postgres — already there),
   and returns to the HTTP handler, which responds to the user.
3. The next user message rehydrates `PipelineState` from Postgres and resumes at
   `state.stage`.

This is exactly today's `pending_plan` flow, generalized to every pause point.

### When to actually adopt LangGraph

Adopt it the day one of these is the task in front of you — not before:

- **Resumable human-in-the-loop via checkpointer** — when hand-maintaining the
  pause/resume state machine in Postgres becomes the pain, swap to LangGraph's
  `interrupt()` + Postgres checkpointer.
- **Live per-node streaming to the Activity panel** — when you want agent
  progress to stream node-by-node into the UI (the differentiated feature).

Because the agents are already `(state) -> state`, that migration is swapping the
shell, not rewriting the agents. (`langgraph` is a separate package from
`langchain`; nodes are plain functions calling any provider — no LangChain
coupling required.)

---

## 5. Multi-provider LLM (DEV-2) — prerequisite, independent track

`utils/tool_use.py` is welded to Bedrock: `client.converse(...)`, Bedrock
message/tool shapes, Nova model ids. Every agent runs through it. Letting users
pick free models (Groq / OpenRouter / HuggingFace) requires abstracting it. This
work is needed **regardless of the pipeline** and is **orthogonal to LangGraph**
(a node still calls a provider-agnostic function inside it).

### Shape

```
backend/utils/llm/
├── base.py            # LLMProvider protocol: run_tool_loop(...) -> {text, messages}
│                      # + a provider-neutral internal message/tool representation
├── bedrock.py         # current tool_use.py logic (Converse API)
├── openai_compat.py   # Groq + OpenRouter (both are OpenAI chat-completions + tools)
└── huggingface.py     # HF Inference — SEE CAVEAT
```

- Groq and OpenRouter share **one** adapter (OpenAI-compatible, tool calling works).
- Bedrock Converse and OpenAI chat-completions have **different** message + tool
  schemas → define one internal representation and translate at each boundary.

### Hard caveat — tool calling

The entire agent design depends on **tool/function calling**. Many free HF
models have weak or no native tool calling. Options, decide before promising
"use any free model":
- Restrict the free-model menu to **tool-capable** models only, or
- Implement a **JSON-prompt fallback** path for models without native tools.

This must be resolved as part of DEV-2, not after.

---

## 6. Real cost estimation (replaces LLM-guessed `$8.47`)

The plan gate is the screen where trust matters most; the model's **hallucinated**
cost is replaced with a real estimate. Two sources, in order:

- **Live AWS Pricing API** (`pipeline/pricing_api.py`) for the flat-rate resources
  where prices drift/vary most (EC2/RDS/ElastiCache/NAT Gateway/Load Balancer). Pinned
  to the us-east-1 pricing endpoint; the region is passed as a **`regionCode` filter**
  (no hardcoded region→location-name map — the API resolves it, so all regions work).
  Results cached process-wide (24h TTL — list prices are account-independent).
- **Static price table** (`pipeline/cost.py`) for everything else, and as the fallback
  whenever the live lookup is unavailable (no `pricing:GetProducts` permission,
  unmapped region/engine, throttle). Every breakdown line records its `source`.
- Usage-based services stay `$0 base + usage-based` — no source can know traffic/storage
  ahead of time. Runs in `validation_node` after Tier-1, feeds the gate.

Why not a web search for prices? It would re-introduce non-determinism/scraping on the
one screen that must be trustworthy; the Pricing API is the authoritative, structured,
cacheable source. (Discussed 2026-06-27.)

---

## 7. Build sequence (phased — each phase shippable)

**Phase 0 — Provider abstraction (DEV-2). ✅ DONE (2026-06-27).** `tool_use.py`
refactored into `utils/llm/` (`base.py` provider-agnostic loop, `bedrock.py`,
`openai_compat.py` for Groq/OpenRouter). HF deferred (tool-calling). `tool_use.py`
kept as a back-compat shim. Provider via `LLM_PROVIDER` env; `run_tool_loop(...,
provider=...)` hook threaded through `run_architect`/`run_executor`. Tests added.

**Phase 1 — Orchestrator skeleton. ✅ DONE (2026-06-27).** Added `pipeline/state.py`
(`PipelineState`) + `pipeline/orchestrator.py` (`run_turn` + `architect_node`/
`executor_node`, the `(state) -> state` signature). `routes/chat.py` now builds a
`PipelineState`, calls `run_turn` in a thread, and persists/responds off
`state.outcome` (conversation | plan_proposed | executed | cancelled). Behavior
unchanged; confirm gate generalized into the orchestrator. `test_orchestrator.py`
covers all four outcomes; chat integration-test patch targets repointed.

**Phase 2 — Requirements Agent. ✅ DONE (2026-06-27).** `agents/requirements.py`
is the front door: thorough intake (one question at a time with options/tradeoffs,
per the user's choice) plus Q&A triage (answers questions/lookups directly via the
shared inspection tools). Emits `<requirements-complete>{spec}</requirements-complete>`;
the orchestrator hands that spec to the Architect in the same turn. Architect is now
plan-only (conversational mode removed); read-only inspection tools extracted to
`agents/inspection.py` and shared by both. Tests: `test_requirements.py`,
`test_inspection.py` (moved from `test_architect.py`), orchestrator + chat tests
updated for the front-door flow.

**Phase 3 — Validation. ✅ DONE (2026-06-27).** `pipeline/validation.py` (Tier-1
deterministic checks) + `_tier1_refine_loop` in the orchestrator (loops back to the
Architect, stops on convergence/non-improvement, `MAX_VALIDATION_ROUNDS=4` backstop).
`agents/critic.py` (Tier-2 single LLM pass → `{blocking_issues, suggestions}`,
advisory/degrades to empty, never loops). Findings surfaced at the user gate in
`chat.py`. Tests: `test_validation.py`, `test_critic.py`, orchestrator loop/surface tests.

**Phase 4 — Real cost estimation. ✅ DONE (2026-06-27).** `pipeline/cost.py` — static
us-east-1 price table; usage-based services reported as $0 base + note. `validation_node`
overwrites the plan's `estimated_monthly_cost` with the computed value + `cost_breakdown`.
Tests: `test_cost.py`.

**Phase 5 — Validator + Summary. ✅ DONE (2026-06-27).** `pipeline/validator.py`
(post-deploy `get_resource_status` health checks, never raises) + `agents/summary.py`
(plain-English wrap-up via tool-free `run_completion`, falls back to executor text).
Both wired into `executor_node`. Tests: `test_validator.py`, `test_summary.py`,
orchestrator executed-path tests.

**Phase 6 — LangGraph. ✅ DONE (structure + streaming, 2026-07-01).** Orchestrator rebuilt
as a `StateGraph` (nodes + conditional edges + the real validate→architect cycle); agents
untouched. **Live per-node streaming** added (`stream_turn` + SSE `POST /api/chat/stream`).
Remaining/optional: the **checkpointer + `interrupt()`** to move cross-request pause/resume
out of Postgres into LangGraph (needs a Postgres checkpointer + moving `aws_session` to
runtime config). See §4.

---

## 8. Decisions locked in this session

- Multi-agent is the design; Executor stays an LLM agent (not plain code).
- Botocore per-resource tools (DEV-4) were the correct override of the old
  "6 generic tools" idea.
- The critic is a real loop, but: deterministic Tier-1 loops + single LLM Tier-2
  pass; terminate on convergence, not a fixed count; severity-gate so only
  blocking issues loop; user adjudicates judgment calls.
- Plain `pipeline.py` orchestrator now; agents shaped as `(state) -> state`;
  LangGraph deferred until resumable-HITL or live-streaming is the actual task.
- Multi-provider (Bedrock + Groq/OpenRouter/HF) via a `utils/llm/` abstraction;
  hard tool-calling caveat for free HF models.
- Replace LLM-guessed cost with a deterministic estimate.
- Bodyguard: unchanged this round.
- `context.md` was superseded by this document and has been deleted.
```
