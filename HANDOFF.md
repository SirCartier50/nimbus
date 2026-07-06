# Nimbus AI — Session Handoff

> Continuity doc for picking up work in a new Claude Code session (e.g. on another
> machine). The conversation transcript and file-based memory are local to the
> machine they were created on and do NOT travel with the repo — this file does.
> Read this together with `context.md` (the agent-architecture design briefing).

---

## What Nimbus Is

Agentic AWS management. Users describe infrastructure in plain English; AI agents
plan, deploy, and monitor it. Originally built for the Amazon Nova AI Hackathon 2026.
Goal now: make it production-ready and publicly deployable.

**Stack:** FastAPI (Python) backend, Next.js 16 + TypeScript frontend, Amazon Bedrock
(Nova) for LLM, boto3 for AWS, Clerk for auth, PostgreSQL (Supabase) for persistence.

**Three agents today:** Architect (plans), Executor (deploys), Bodyguard (background
monitoring daemon that auto-stops idle EC2).

---

## Done This Session (already committed & pushed)

- **Clerk backend auth** — `backend/auth.py` middleware verifies Clerk JWTs (RS256 via
  JWKS), protects `/api/*`, leaves `/health` public. Frontend uses
  `frontend/app/lib/useAuthFetch.ts` hook to attach the token.
- **Docker** — multi-stage `backend/Dockerfile` + `frontend/Dockerfile` (Next standalone),
  `docker-compose.yml`, `.dockerignore` files. Secrets injected at runtime, not build args.
- **Security hardening** — path-traversal fixes in `backend/routes/workspace.py`
  (normpath + workspace-boundary checks), env-driven CORS in `main.py`, session cap
  (`_MAX_SESSIONS = 500`) + input validation (`max_length=4000`) in `routes/chat.py`.
- **Env templates** — `.env.example`, `backend/.env.example`, `frontend/.env.local.example`.
  Real `.env` files are gitignored — recreate them on the new machine from the templates.
- **DB scaffolding** — empty `backend/db/` (engine.py, __init__.py), ready for DEV-3.
- **`backend/utils/tool_use.py`** — shared Bedrock converse API tool-use loop.

## DEV-3 — DONE (built, migrated, route-wired)

Schema designed, SQLAlchemy models written, Alembic migration generated/applied to the
real Supabase Postgres instance, and `routes/chat.py` + `routes/settings.py` rewired off
in-memory dicts onto the DB. See `backend/db/SCHEMA_NOTES.txt` for full schema detail.
Summary:
  - `users` — id (UUID PK), clerk_user_id (unique), email, created_at
  - `user_settings` — user_id (PK/FK), aws_access_key_id (Fernet encrypted),
    aws_secret_access_key (Fernet encrypted), github_repo_url, updated_at
  - `sessions` — id (UUID PK), user_id (FK), title, model, region (default us-east-1),
    history (JSONB), pending_plan (JSONB), plan_is_destructive, generated_files (JSONB),
    created_at, updated_at
  - `deployments` — id (UUID PK), user_id (FK), session_id (FK), plan (JSONB),
    results (JSONB), status, created_at
  - Dashboard resource data is NOT persisted — pulled live from boto3 each time.
    Short-TTL Redis cache is the right answer later (PROD-3), not a DB table.
  - free_tier_mode is NOT in settings — it's a per-request toggle already on ChatRequest.
  - region is NOT in settings — it's per-session (in sessions table).
  - New helper modules: `backend/db/deps.py` (`get_db()` FastAPI dependency),
    `backend/db/crud.py` (`get_or_create_user`, race-safe on `clerk_user_id`),
    `backend/utils/crypto.py` (Fernet encrypt/decrypt, key in `FERNET_KEY` env var).
  - `routes/chat.py`: sessions/history/pending_plan/generated_files persisted per-user
    (`_get_owned_session` scopes every lookup by `id` AND `user_id` — BOLA/IDOR-safe).
    Every executor run also writes a `Deployment` row.
  - `routes/settings.py`: AWS creds Fernet-encrypted into `user_settings`, GitHub repo
    URL persisted per-user. Verified end-to-end with a live smoke test against Supabase.
  - **Gap closed (2026-06-23):** `agents/executor.py` and `routes/dashboard.py` now
    consume per-user AWS credentials via `utils/user_aws.get_user_boto3_session`
    instead of process-global `os.environ`. See finding #2 below for detail.

- **engine.py explained + template given** — user is writing it themselves to learn.
  Key points: `create_async_engine(DATABASE_URL)`, `async_sessionmaker(expire_on_commit=False)`,
  `DeclarativeBase` defined here to avoid circular imports. DATABASE_URL format:
  `postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DATABASE` (Supabase connection string,
  swap `postgresql://` → `postgresql+asyncpg://`).

- **Production readiness review (full codebase audit) — status as of 2026-06-22.
  All 7 findings closed as of 2026-06-23:**
  1. [x] `authFetch` ReferenceError in `EditorPanel`/`TerminalPanel` (`chat/page.tsx`) — fixed
     by calling `useAuthFetch()` inside each panel and adding `authFetch` to the
     dependent `useCallback`/`useEffect` dep arrays.
  2. [x] AWS credentials were GLOBAL across all users — fully fixed. Added
     `utils/aws_clients.get_boto3_session(access_key_id, secret_access_key, region)`
     (sync factory) and `utils/user_aws.get_user_boto3_session(db, user_id)` (async,
     decrypts the user's Fernet-encrypted creds from `user_settings`). Every
     `get_*_client()` in `aws_clients.py` now takes an optional `session` param.
     `routes/chat.py` and `routes/dashboard.py` build a per-request session and pass
     it (as `aws_session`) into `run_architect`/`run_executor`/dashboard resource
     functions, which bind it into their tool handlers via closures — never a shared
     global. Removed the `os.environ` mirroring stopgap from `settings.py` entirely.
     (Bodyguard's background patrol still uses the global/env credential path — it's
     a singleton daemon, not yet per-user; that's the separate, larger "Bodyguard
     should be its own process" item from the Eng review, not part of this fix.)
  3. [x] Bodyguard (`bodyguard.py`) now filters `describe_instances` by
     `tag:ManagedBy=Nimbus` in `_handle_list_running_instances`, so it can only ever
     see/stop Nimbus-tagged instances.
  4. [x] `_free_tier_mode` global removed from `executor.py`. `run_executor()` now binds
     `free_tier_mode` and `aws_session` per call via closures over the handler dict —
     no shared mutable state between concurrent requests.
  5. [x] `executor.py` S3 delete (`_handle_delete_s3`) now uses the `list_objects_v2`
     paginator instead of a single unpaginated call, so buckets with >1000 objects
     delete correctly.
  6. [x] Removed the dead `autoStop`/`budgetAlerts` toggles from `settings/page.tsx`
     (they only wrote to `localStorage` — nothing backend-side ever read those keys,
     and Bodyguard is a global daemon so a per-browser toggle couldn't gate it
     anyway). Replaced with a static note that auto-stop is always on. Revisit once
     Bodyguard is made per-user/per-process.
  7. [x] Landing page footer changed to "Powered by Amazon Bedrock"; also removed the
     same hackathon phrase from the FastAPI app `description` in `main.py` (was
     visible in `/docs`).

- **CEO + Engineering reviews done (inline):**
  CEO: Product concept is sound. Core risk is trust (real money, real AWS). Bodyguard is
  the most differentiated feature — double down on it. Remove hackathon branding. Target
  indie devs / side projects first. Requirements Agent is the biggest missing UX piece.
  Eng: Single-process globals block horizontal scaling. Bodyguard should be a separate
  process in production. Config-driven executor refactor (DEV-4) must happen before
  adding more AWS coverage. Per-user credential injection needed at the request level via
  a `get_boto3_session(user_id)` helper that decrypts Fernet creds from DB per request.

### To resume on a new machine
```bash
git clone https://github.com/SirCartier50/nimbus.git && cd nimbus
# Recreate the 3 secret files from their .example templates (NOT in git):
#   .env, backend/.env, frontend/.env.local
git config --global user.email "mignotmesele@gmail.com"   # consistent commit identity
```

---

## Decisions Made This Session

### Database (DEV-3 — in progress, user is doing this to learn PostgreSQL)
- **Choice:** PostgreSQL via Supabase (managed hosting, looks good for production, SQL).
- **ORM:** SQLAlchemy 2.0 style (DeclarativeBase, Mapped, mapped_column) + async (asyncpg).
  Migrations via Alembic. Deps already in `requirements.txt`.
- **Schema (designed, not yet built):** `users`, `sessions`, `deployments`, `user_settings`.
  Use JSONB columns for flexible data (chat history, plans).
- **Per-user AWS credentials:** YES — bigger refactor; agents currently use a single
  global credential. Encrypt stored creds with **Fernet** (reversible) — NOT SHA256
  (SHA256 is one-way hashing; boto3 needs to decrypt and use the keys).
- **Not persisting:** bodyguard alerts/logs.
- **Next steps:** finish schema -> SQLAlchemy models -> first Alembic migration ->
  wire `_sessions` dict in chat.py to the DB.

### Chat-page UI (the right-hand panel)
Current `frontend/app/chat/page.tsx` right panel = 480px split 3 ways: Activity (25%),
Editor (40%), Terminal (35%). Decided:
- **REMOVE Editor Panel** — it's a dumb textarea over a temp workspace; generated configs
  are already downloadable from the chat (FilesCard). No AI connection. Users edit in VS Code.
- **REMOVE Terminal Panel** — temp workspace + subprocess execution is an attack surface
  with little real value; GitHub-link flow is niche; bodyguard logs already on `/terminal` page.
- **KEEP & EXPAND Activity Panel** — this is what makes Nimbus feel agentic; shows agent
  reasoning live. Strongest panel.
- **ADD a Live Resource Map** (chosen replacement) — card-based view of currently deployed
  resources with status, reusing the existing `/api/dashboard/resources` endpoint. Gives
  visual feedback after deploy without leaving chat. Layout: Activity (~40%) + Resource Map (~60%).
- **Backend cleanup:** delete/gut `backend/routes/workspace.py` once panels are gone (removes
  subprocess execution + temp-file + GitHub-credential attack surface). Keep `write-files`
  only if file generation still needs to land files somewhere.

### Agent architecture (see context.md for the full briefing)
User's core concern: current `executor.py` has one hardcoded tool per AWS action
(create_ec2, stop_ec2, create_s3_bucket, ...). That doesn't scale — every new service =
another tool. Agreed direction:
- **Config-driven tools** — replace static per-action tools with ~6 generic ones:
  `create_resource(resource_type, config)`, `get_resource_status`, `update_resource`,
  `delete_resource`, `list_resources`, `validate_config`. The LLM constructs the AWS
  config dict; the backend routes `resource_type` to the right boto3 call.
- **Add a Requirements Agent** — conversational intake, one question at a time with
  options/tradeoffs, builds a structured spec before the Architect plans. Biggest missing UX piece.
- **Add a Validator Agent (plain code)** — confirm resources actually came up healthy;
  don't trust a 200 from boto3.
- **Only 3 LLM agents** (Requirements, Architect, Summary); Cost/Approval, Executor,
  Validator, Bodyguard are plain Python.
- **Phase it, don't rewrite at once:** (1) Requirements Agent, (2) config-driven Executor +
  Validator, (3) provider abstraction + Summary agent.

#### My caveats on context.md (don't follow it blindly)
- "The LLM already knows AWS specs" is mostly true but models hallucinate AMI IDs / param
  names. Add a server-side schema registry (`resource_type -> required fields + allowed
  values`) to validate configs before they hit boto3.
- Don't build `base_provider.py` + `gcp/` stubs yet — build AWS config-driven first,
  structured so a base interface can be extracted later. Avoid premature abstraction.
- context.md assumes a fresh `app/` file layout; our real layout is `backend/agents`,
  `backend/routes`, `backend/utils`. Adapt the ideas, don't copy the file tree.

### Session / context optimization
- Session history exists (`session["history"]` in chat.py) but is in-memory — dies on
  restart. DEV-3 fixes persistence.
- Context optimization (sliding window / token-count trimming / summarizing old turns) is
  a **post-launch** concern, not a blocker. History currently grows unbounded per session.

---

## Task List (lives only in the session harness — reproduced here)

Priority / security (do before dev work):
- [x] **SEC-1** Protect all backend API endpoints with auth — DONE (Clerk middleware)
- [ ] **SEC-2** Add rate limiting to API endpoints
- [x] **SEC-3** ~~Encrypt stored AWS credentials (Fernet)~~ **SUPERSEDED 2026-07-04** —
      no longer stores AWS credentials at all. Migrated to STS AssumeRole (see the
      "STS AssumeRole migration" section below) — `utils/crypto.py` and the Fernet
      columns are gone; nothing long-lived is stored for the user's AWS access.

Development:
- [ ] **DEV-1** Finish in-progress refactor — stabilize tool_use.py integration (mostly done; commit/verify)
- [~] **DEV-2** Replace Amazon Nova with a free/open LLM — Phase 0 DONE (2026-06-27):
      provider abstraction built. `utils/tool_use.py` is now a back-compat shim;
      real code lives in `utils/llm/` (`base.py` = provider-agnostic tool loop;
      `bedrock.py` = default Nova provider; `openai_compat.py` = Groq + OpenRouter,
      both OpenAI-compatible, with Bedrock<->OpenAI format translation; `__init__.py`
      = `get_provider()` factory + `run_tool_loop()` convenience). Canonical internal
      format is Bedrock Converse shape — non-Bedrock providers translate to/from it,
      so all 3 agents + chat.py are unchanged and still default to Bedrock. Provider
      chosen via `LLM_PROVIDER` env (bedrock|groq|openrouter|huggingface — HuggingFace
      ENABLED 2026-07-04 via its OpenAI-compatible Inference Providers router
      `https://router.huggingface.co/v1`, `HF_TOKEN`+`HF_MODEL`; the tool-calling caveat
      is met by choosing a tool-capable model, see below). `openai` added to
      requirements. Tests: `test_openai_compat.py` (translation layer) added;
      `test_tool_use.py` patch target moved to `utils.llm.bedrock`. Full suite green
      (84 passed, 24 skipped). REMAINING: let the pipeline/UI pass a per-user provider
      choice through `run_tool_loop(..., provider=...)` (the hook exists, not yet wired
      to a user setting). See PIPELINE_PLAN.md §5.
- [x] **DEV-3** Add database — persist chat sessions, user configs, deployment history — DONE
      (models, Alembic migration applied to Supabase, chat.py/settings.py route-wired)
- [x] **DEV-4** Expand agent tool coverage — full AWS API access — DONE (2026-06-24), see
      "DEV-4 — DONE" section below. Built as botocore-sourced per-resource tools, NOT the
      generic `create_resource(resource_type, config)` blob originally specced — user
      explicitly rejected that approach mid-session in favor of full AWS-sourced fidelity.
- [x] **DEV-5** ~~Improve UI — chat, dashboard, terminal, editor (remove editor/terminal, add resource map)~~
      — DONE 2026-07-05 for the chat page (editor/terminal removed, resource map
      added, plus session switcher + model selector — see "DEV-5" section below).
      The standalone `/dashboard` and `/terminal` pages were already built in an
      earlier session and untouched here.

Production:
- [ ] **PROD-2** Production config — CORS, env management, deployment setup
- [ ] **PROD-3** Add Redis — LLM prompt cache, session KV store
- [ ] **PROD-4** Kubernetes deployment
- [ ] **PROD-5** Error handling, input validation, security hardening
- [ ] **PROD-6** Observability — Grafana + Prometheus
- [ ] **PROD-7** Production testing — k6 load tests + integration suite

Testing:
- [ ] **TEST-1..7** Unit/integration/component tests (agent handlers, tool_use loop, plan
      parsing, chat endpoint, dashboard/settings/workspace endpoints, bodyguard, frontend)

Future:
- [ ] **FUTURE-1** Multi-cloud support — GCP
- [ ] Subscription/tier system (Free pay-per-usage / Pro / Max) with rate limiting and
      5-hour reset windows + model selection — depends on DB + payment + DEV-2.

---

## DEV-4 — DONE (2026-06-24)
**What shipped, and why it's not what the original plan said:** `context.md`'s original
plan (and the Eng review) called for 6 generic tools — `create_resource(resource_type,
config: dict)` etc. — relying on the model's memory of AWS APIs. The user explicitly
rejected this mid-session: *"the only way to truly do this is by providing the model
with every type of tool for everything as if we created an interface for the model to
use boto3."* What got built instead:

- `backend/providers/aws_schema.py` — walks botocore's locally-bundled AWS service
  models (the same data that generates the AWS console's forms) into JSON-Schema dicts.
  Two outputs per operation: a depth/enum-capped `generate_tool_schema()` for what
  Bedrock actually sees, and a full-fidelity `generate_validation_schema()` used only
  for local `jsonschema` validation before any boto3 call.
- `backend/providers/aws_registry.py` — the 15-resource-type registry (`ec2_instance`,
  `s3_bucket`, `rds_instance`, `lambda_function`, `vpc`, `subnet`, `security_group`,
  `ecs_cluster`, `load_balancer`, `api_gateway`, `dynamodb_table`, `elasticache`,
  `cloudfront`, `nat_gateway`, `iam_role`). Encodes, per type: create/describe/delete/
  list operation names, the describe-vs-delete id-parameter shape (several EC2
  sub-resources take a list for describe but a singular id for delete), and which of 5
  distinct tagging mechanics applies (EC2's `TagSpecifications` wrapper, a `Tags=[{Key,
  Value}]` list, ECS's lowercase `tags=[{key,value}]`, a `Tags={k:v}` map, or S3/
  CloudFront's separate post-create tagging call). All verified directly against the
  installed botocore package, not assumed.
- `backend/providers/aws_dispatch.py` — shared read-only dispatch (`get_resource_status`,
  `list_resources`) used by both `architect.py` (conversational Q&A) and `executor.py`
  (post-create verification).
- `backend/agents/executor.py` — rewritten. One `create_<resource_type>` Bedrock tool per
  registry entry (15 total), generated straight from botocore — the model gets real AWS
  field names/enums/docs, not a hand-maintained approximation. Plus generic
  `get_resource_status`/`list_resources`/`delete_resource` tools (these don't need
  per-type schemas — they just take a resource_type + id) and a dedicated
  `stop_ec2_instance` (the one state-transition action outside CRUD). Every create config
  is `jsonschema`-validated against the full-fidelity schema before reaching boto3.
- `backend/agents/architect.py` — plan format updated: steps now carry `resource_type`
  (one of the 15) + `config` using real AWS field names, instead of the old 9 hardcoded
  action names with simplified params. Its own inspection tools are now the same generic
  `list_resources`/`get_resource_status` rather than 4 hand-written per-service tools.
- All of the above verified with botocore-shape introspection + mocked-client unit tests
  (no real AWS calls) covering all 5 tag strategies, the describe/delete id-shape split,
  and required-field validation rejection — not just read by inspection.

**Known gaps / deliberately out of scope this pass:** no `update_resource` (AWS update
operations vary too much per service — `ModifyDBInstance` vs `UpdateFunctionConfiguration`
— to generalize without designing that separately); CloudFront's distribution must
already be disabled before delete will succeed (not enforced, just documented in the
registry); IAM role creation has no way to attach a policy after creation (only
`_ensure_lambda_role`'s bootstrap path does this internally) — a model-driven IAM role
for a new Lambda function won't have a usable execution policy attached.

## Bodyguard per-user refactor — DONE (2026-06-24)
**What changed:** Bodyguard was a single background daemon task patrolling whatever AWS
account the process env vars pointed to, with one global `state` dict — alerts/logs for
every user were the same object, so any logged-in user saw everyone's bodyguard state.

- `db/crud.py` — added `list_users_with_aws_credentials(db)`, joins `User`/`UserSettings`
  and filters to users who've actually connected AWS creds.
- `agents/bodyguard.py` — `state` is now `dict[str(user_id), dict]`, one isolated slot per
  user (`_get_user_state`, lazily created). `_daemon_active` is the only remaining
  process-global (whether the loop itself is alive, not user data). The loop
  (`_bodyguard_loop`) opens a DB session each cycle, enumerates users with credentials via
  `list_users_with_aws_credentials`, builds each one's `boto3.Session` via
  `get_user_boto3_session` (the same Fernet-decrypt helper chat/dashboard already use),
  and runs one patrol per user sequentially with that user's session + state slot bound
  via closures (`_build_handlers`) — never globals. `get_status`/`get_alerts`/
  `mark_alert_read` all now take `user_id` and only ever touch that user's slot.
- `routes/dashboard.py` — `/dashboard`, `/dashboard/alerts` (GET+POST), and
  `/dashboard/bodyguard` now all fetch the current user via `get_or_create_user` and pass
  `str(user.id)` through, instead of calling bodyguard's status functions with no user
  context at all.
- Verified with mocked tests (no real AWS/DB/Bedrock): per-user log/alert isolation,
  lazy state creation for never-patrolled users, `mark_alert_read` not cross-contaminating
  other users' alerts, and `_run_patrol`'s session/state binding falling back correctly
  per-user when the simulated Bedrock call fails. Full `main.py` import/app-construction
  verified clean after the change.

**Known gap, deliberately deferred:** users are patrolled sequentially within one
`CHECK_INTERVAL` (300s) cycle, not concurrently — fine at indie/side-project scale, but
will need `asyncio.gather` with bounded concurrency (or a proper task queue) once the
user count is large enough that one full sweep risks exceeding 300s. Not worth building
ahead of actual scale.

## Agent pipeline redesign — see PIPELINE_PLAN.md (NEW authoritative design)
A 2026-06-27 design session produced `PIPELINE_PLAN.md`, which **supersedes
`context.md`**. Key decisions: multi-agent is intentional (Executor stays an LLM
agent, not plain code); the critic is a real loop but split into a deterministic
Tier-1 (loops safely, no false positives) + a single LLM Tier-2 pass whose findings
the *user* adjudicates; agents are built as `(state) -> state` functions; LangGraph
deferred until resumable-HITL or live node-streaming is the actual task.

Progress against PIPELINE_PLAN §7:
- **Phase 0 (provider abstraction / DEV-2): DONE** — see DEV-2 entry above.
- **Phase 1 (orchestrator skeleton): DONE (2026-06-27)** — `backend/pipeline/`
  (`state.py` = `PipelineState`; `orchestrator.py` = `run_turn` + `architect_node`/
  `executor_node`). `routes/chat.py` rewired to drive the orchestrator; behavior
  unchanged, confirm gate generalized. `tests/unit/test_orchestrator.py` covers all
  four outcomes. Full suite: 90 passed, 24 skipped (chat integration tests skip
  without a local Postgres; their patch targets were repointed to
  `pipeline.orchestrator`).
- **Phase 2 (Requirements Agent): DONE (2026-06-27)** — `agents/requirements.py`
  is the pipeline front door. Decisions made this session: intake is **thorough**
  (full context.md checklist, one Q at a time w/ options+tradeoffs) and Requirements
  **triages** (answers Q&A/lookups directly; only completed builds hand off). It
  emits `<requirements-complete>{spec}</requirements-complete>`; the orchestrator
  feeds that spec to the Architect in the same turn. Architect is now **plan-only**
  (conversational mode deleted); shared read-only tools live in `agents/inspection.py`.
  `chat.py` needed no change (requirements-incomplete/Q&A both map to the existing
  "conversation" outcome). Tests: `test_requirements.py` + `test_inspection.py`
  (replacing `test_architect.py`); orchestrator + chat integration tests rewired.
  Full suite: 97 passed, 24 skipped.
- **Phase 3 (validation): DONE (2026-06-27)** — Tier-1 `pipeline/validation.py`
  (deterministic checks: structure, valid action/resource_type, create-needs-config,
  delete-needs-id, free-tier rules, in-plan prerequisite ordering) + the orchestrator's
  `_tier1_refine_loop` (loops the plan back to the Architect, stops on convergence /
  non-improvement, `MAX_VALIDATION_ROUNDS=4` backstop). Tier-2 `agents/critic.py`
  (single LLM pass → `{blocking_issues, suggestions}`; advisory — degrades to empty on
  bad JSON / model error; NEVER auto-loops). Findings surfaced to the user at the
  approval gate in `chat.py`.
- **Phase 4 (real cost): DONE (2026-06-27)** — `validation_node` writes
  `estimated_monthly_cost` + `cost_breakdown` onto the plan. Two sources: the **live
  AWS Pricing API** (`pipeline/pricing_api.py`) for EC2/RDS/ElastiCache/NAT/ALB (cached
  24h, pinned to us-east-1 endpoint, region passed as a `regionCode` filter — no
  hardcoded region→location map), with the **static table**
  (`pipeline/cost.py`) as fallback for everything else and whenever the live lookup
  fails (no `pricing:GetProducts` perm / unmapped region / throttle). Every breakdown
  line carries a `source` field. Usage-based services show `$0 base + usage-based`.
  NOTE: the live path needs `pricing:GetProducts` on the user's AWS creds; without it,
  it silently falls back to static — works either way.
- **Phase 5 (Validator + Summary): DONE (2026-06-27)** — `pipeline/validator.py`
  (post-deploy health via `get_resource_status`, never raises) and `agents/summary.py`
  (plain-English wrap-up; falls back to the executor's own text if the model is down),
  both wired into `executor_node`. New tool-free `run_completion` added to `utils/llm`
  (Bedrock/OpenAI adapters now omit tools when none are passed).
- **LangGraph migration: DONE (structure, 2026-07-01)** — `pipeline/orchestrator.py`
  is now a real `langgraph` `StateGraph`, replacing the hand-rolled `run_turn` routing
  and the `_tier1_refine_loop` `while` loop. Nodes: requirements/architect/validate/
  finalize/executor/cancel; conditional edges for routing; and a genuine graph **cycle**
  `validate → architect → validate` for Tier-1 refinement (convergence-based
  `route_after_validate`, `MAX_VALIDATION_ROUNDS` backstop). Each node returns a dict of
  state updates; `run_turn` `invoke`s the compiled graph and rebuilds a `PipelineState`
  (LangGraph `.invoke()` returns a plain dict). **Agents/prompts/tests-of-agents were
  NOT touched** — only the ~30-line control shell, exactly because nodes were already
  `(state)->state`. `chat.py` unchanged; cross-request persistence still Postgres.
  `langgraph>=1.0.0` added to requirements.
- **LangGraph streaming: DONE (2026-07-01)** — `pipeline/orchestrator.stream_turn()` uses
  `graph.stream(stream_mode="updates")` to yield a progress event per node as each agent
  finishes (the Tier-1 refine cycle surfaces `architect` twice = visible refinement), then
  a final event with the rebuilt state. New SSE endpoint `POST /api/chat/stream`
  (`routes/chat.py`) bridges the sync graph stream to the async response via a thread+queue;
  `/chat` and `/chat/stream` now share `_finalize_turn` (identical persistence/response).
  This is the "activity feed" differentiator — frontend still needs to consume it (DEV-5).
  Tests: 4 new streaming unit tests in `test_orchestrator.py` + a stream integration test.
  Full suite: 145 passed, 25 skipped.
  REMAINING (optional): LangGraph checkpointer + `interrupt()` to own pause/resume
  (replacing the Postgres `pending_plan` rehydrate) — needs a durable Postgres checkpointer
  (MemorySaver isn't multi-worker/restart-safe) AND moving the non-serializable
  `aws_session`/`provider` out of checkpointed state into runtime `config`.
- **Cloud Control generic path: WIRED + ENABLED (2026-07-04).** The Architect now emits
  either a curated short name (preferred) OR an `AWS::Service::Resource` CloudFormation
  type for the long tail; the Executor routes CFN types to `create_resource_by_type`
  (`run_executor(use_cloud_control=True)` is passed from `executor_node`). Tier-1
  validation (`pipeline/validation.py`) accepts CFN types (`"::" in rt`) and skips the
  per-service free-tier/prereq checks for them (documented gap: Tier-1 can't enforce
  free-tier on arbitrary CFN types — the Architect prompt guards it instead). Cost
  (`pipeline/cost.py`) marks generic types "not estimated — non-standard resource type"
  (source `unknown`, formatted "+ unestimated resources") rather than fabricating a
  number. Hybrid stands: curated 15 = precise cost + special actions (stop/empty-delete);
  generic = breadth. Tests added: validation (CFN accepted/rejected), cost (unestimated),
  orchestrator (use_cloud_control passthrough). Full suite: 163 passed, 25 skipped.
  Underlying provider built earlier —
- **Cloud Control generic executor path: BUILT + tested (2026-07-01), now LLM-wired (above).**
  `providers/cloud_control.py` — one uniform CRUD interface over ~any CloudFormation
  resource type via the boto3 `cloudcontrol` client (`create_resource(TypeName,
  desired_state)`, `get_resource`, `list_resources`, `delete_resource`). Handles the
  async create/delete (polls `get_resource_request_status` to a terminal state), injects
  the uniform `ManagedBy=Nimbus` tag (CFN `[{Key,Value}]` shape) with a retry-without-tags
  fallback for resource types that reject Tags, and paginates list. Wired into
  `executor.py` as four generic tools (`create_resource_by_type` / `get_` / `list_` /
  `delete_`), gated behind `run_executor(use_cloud_control=True)` — **off by default**, so
  the live per-service registry path is unchanged. This is the "breadth over any AWS
  service" answer to the 15-type registry cap (chosen over consuming an AWS MCP server —
  MCP would add a subprocess + per-user-cred complexity to reach the same Cloud Control
  API we call directly in-process). Tests: `test_cloud_control.py` (10) + 3 executor CC
  tests, all with mocked boto3 (no LLM, no real AWS). REMAINING (the "with LLM" step, not
  done): teach the Architect to emit CFN TypeNames + desired-state for the long tail,
  flip `use_cloud_control` on, and decide validation/free-tier handling on this path
  (per-service schema validation doesn't exist for arbitrary CFN types — would come from
  CloudFormation `describe_type`). Keep the curated registry for the special *actions*
  Cloud Control can't do (stop/start EC2, empty-then-delete S3, Lambda-role bootstrap).
- **ALL PIPELINE PHASES (0-5) DONE.** Full suite: 128 passed, 24 skipped (the skips
  are AWS/DB integration tests needing a live Postgres — not available in the sandbox;
  their mocks/patch-targets are updated to the new flow). Phase 6 (LangGraph) remains
  deliberately deferred per PIPELINE_PLAN §4. Agent prompts themselves are only
  validated on the first real run against Bedrock + Supabase.

## Clerk Billing + backend claim checks — DONE (2026-07-04)

Both outstanding Clerk items closed this session. **Decision: kept the existing hand-rolled
JWT verification in `backend/auth.py` (PyJWT + Clerk's JWKS endpoint, RS256) instead of
swapping to the `clerk-backend-api` SDK's `authenticate_request()`.** Verified via live
docs before deciding: Clerk's own "manual JWT verification" guide recommends exactly this
JWKS+PyJWT approach for non-JS backends, and the Python SDK's request-adapter contract
(what shape of request object `authenticate_request()` needs — raw ASGI request vs.
`httpx.Request`) was **inconsistent between two official sources** when checked. Given
this is the auth gate for the whole app, swapping to an unverifiable adapter contract was
the wrong risk to take for zero behavioral gain — the existing code was already correct
and is Clerk's documented approach. No `clerk-backend-api` dependency was added.

**What was built (verified against live Clerk docs, not memory — caught that `<Protect>`
from training data is outdated; current component is `<Show>`):**
- `backend/auth.py` — `request.state.claims` now holds the full verified JWT payload
  (previously only `.user_id`). New pure helpers: `get_plan()`/`get_features()` (read the
  reserved `pla`/`fea` session-token claims Clerk Billing populates) and
  `has_plan(claims, slug)`/`has_feature(claims, slug)` (match on the plan/feature slug
  regardless of the `u:`/`o:` user-vs-org scope prefix — same semantics as the frontend's
  `has({ plan })`). Two FastAPI dependency factories, `require_plan("slug")` /
  `require_feature("slug")`, ready to drop onto any route via
  `dependencies=[Depends(require_plan("pro"))]` — **not yet applied to any route**, since
  no tier/feature business rule has been decided (see below).
- `frontend/app/settings/billing/page.tsx` — new page rendering Clerk's `<PricingTable />`
  (confirmed current export via the installed `@clerk/nextjs` package's own `.d.ts`, not
  guessed), in the existing dark/glass shell.
- `frontend/app/settings/page.tsx` — new "Billing & Plan" card showing the current plan
  (via `useAuth().has({ plan: "pro" })`, confirmed present in the installed package) with
  a link to the new billing page.
- Tests: `tests/unit/test_auth.py` (13 cases — pure claim-matching logic + the two
  dependencies exercised through a real `FastAPI`/`TestClient` app, not just called as bare
  functions). Frontend: `npx tsc --noEmit` clean.
- Full backend suite: **175 passed, 25 skipped.**

**What YOU still need to do (can't be done from this session):**
1. **Clerk Dashboard → Billing**: enable Billing, define the actual plan slugs (e.g.
   `free`/`pro`) and any Features. The code above reads whatever slugs you configure —
   nothing is hardcoded beyond the example `"pro"` string in the settings-page display.
2. **Decide what's actually gated.** No product rule exists yet for "which routes/features
   require which plan" — this needs a business decision (e.g. concurrent session limits,
   provider choice, priority support) before `require_plan`/`require_feature` get attached
   to any route. The subscription/tier system item in the Task List below is otherwise
   unblocked as of this session.

## Docker E2E — first real run, 3 real bugs found + fixed (2026-07-04)

First time the stack was actually brought up in Docker end-to-end. Found and fixed,
in order (each reproduced live, not guessed):

1. **`frontend/Dockerfile` used `node:18-alpine`** — Next.js 16 requires Node ≥20.9.0;
   build failed immediately. Bumped all 3 stages to `node:20-alpine`.
2. **`backend/Dockerfile` non-root user couldn't execute uvicorn** — `pip install
   --user` put packages under `/root/.local` (root-owned, not traversable by the
   `appuser` the container switches to); `chown -R appuser:appuser /app` never
   touched `/root/.local`. Switched to a venv at `/opt/venv` (a plain, chown-able
   path) instead — the standard fix for this exact non-root-container pattern.
3. **`auth_middleware` gated `OPTIONS` requests** — CORS preflight never carries an
   `Authorization` header (browser strips it by design on `OPTIONS`), so gating every
   method on `/api/*` permanently 401'd every preflight, breaking CORS for every
   authenticated route regardless of middleware ordering. Fixed: `OPTIONS` now
   bypasses the auth check in `auth.py` and falls through to CORSMiddleware/the
   router; real requests are unaffected (regression-tested in `test_auth.py`).

Plus two environment issues (not code bugs): the root `nimbus/.env` (which
`docker-compose.yml` reads for the Clerk build args — **not** `frontend/.env`, a
common mix-up) didn't exist, and `backend/.env`'s `CLERK_ISSUER` was still the
literal `.env.example` placeholder. Both fixed for this session's setup.

**Verified live end-to-end**, not just "should work": backend health, frontend
render, a direct `SELECT 1` against the real Supabase DB from inside the backend
container, and (after the OPTIONS fix) a real preflight `OPTIONS` request returning
200 while an unauthenticated real request still correctly returns 401.

## STS AssumeRole migration — DONE (2026-07-04)

Replaced stored long-lived AWS access keys with STS AssumeRole (temporary,
auto-expiring credentials) — the "alternative recommended" flow AWS's own console
surfaces when creating an access key. **Full cutover, not a parallel path** — this
is pre-launch with no real users to migrate, so no legacy access-key code was kept.

**Why not swap to it "later":** decided to do this before the GitHub push / prod
hardening, since every day post-launch is a day of real users' stored keys to
migrate instead of zero.

**What changed:**
- **`db/models.py` / new Alembic migration `ea490f2064bf`** — `UserSettings` swaps
  `aws_access_key_id`/`aws_secret_access_key` for `aws_role_arn`/`aws_external_id`.
  Neither new column is Fernet-encrypted — an ARN is an identifier and AWS's own
  guidance is that an external_id only needs to be unique, not secret. **Migration
  applied to the real live Supabase DB this session** (verified via
  `information_schema.columns` before/after) — this is not just a generated file
  sitting unapplied.
- **`utils/crypto.py` deleted** — nothing needs Fernet encryption anymore (confirmed
  via grep it was only used by the two files being rewritten). `FERNET_KEY` removed
  from `.env.example` and `tests/conftest.py`.
- **`utils/aws_role.py`** (new) — `assume_role(role_arn, external_id, ...)` calls STS
  using Nimbus's own service identity (the existing env-level `AWS_ACCESS_KEY_ID`/
  `AWS_SECRET_ACCESS_KEY` — confirmed via live `sts:get_caller_identity()` to be IAM
  user `arn:aws:iam::804306814230:user/botouser`), returns a `boto3.Session` backed
  by temporary credentials, with in-memory per-`(role_arn, external_id)` caching
  until near-expiry (same single-process-cache tradeoff already accepted elsewhere
  in this codebase — Bodyguard state, session history — not durable across a
  restart/multi-worker deploy). `generate_external_id()` mints a fresh id per user.
- **`utils/user_aws.py`** — `get_user_boto3_session(db, user_id)` keeps its exact
  signature (so `chat.py`/`dashboard.py`/`bodyguard.py`/executor call sites needed
  zero changes) but now calls `assume_role()` instead of decrypting stored keys.
- **`routes/settings.py`** — `GET /settings/aws` lazily generates + persists the
  user's `external_id` on first view (must be stable before they deploy the CFN
  stack) and returns it plus `nimbus_principal_arn`; `POST /settings/aws` now takes
  `{role_arn}`, validates it by actually calling `assume_role()` + `get_caller_identity()`
  before persisting, 400s with the real STS error on failure.
- **`infra/nimbus-cross-account-role.yaml`** (new) — the CloudFormation template
  users deploy in their own account: parameterized by `ExternalId` (required),
  `NimbusPrincipalArn` (defaults to the real value above), and `PolicyArn` (defaults
  to `PowerUserAccess`, matching prior onboarding scope). Trust policy allows
  `sts:AssumeRole` from `NimbusPrincipalArn` conditioned on the matching
  `sts:ExternalId`. **Verified structurally** (CFN-tag-aware YAML parse confirming
  parameters/trust-policy/condition/output all well-formed) — **NOT verified via
  AWS's live `ValidateTemplate` API**, because the Nimbus service IAM user
  (`botouser`) lacks `cloudformation:ValidateTemplate` permission (a real, observed
  `AccessDenied`, not assumed). Copied into `frontend/public/` so it's downloadable
  directly from the running app.
- **Frontend** (`settings/page.tsx`, `AWSGate.tsx`) — replaced the access-key/region
  form with: External ID display (+ copy button), a CFN template download link, and
  a Role ARN input. Onboarding 3-step copy rewritten to match. `npx tsc --noEmit` clean.
- **Bug caught by this migration, not by unit tests**: `db/crud.py`'s
  `list_users_with_aws_credentials` still queried the dropped `aws_access_key_id`
  column — Bodyguard's loop crashed on it at container startup
  (`type object 'UserSettings' has no attribute 'aws_access_key_id'`). Unit tests
  didn't catch it because Bodyguard's own tests mock this function entirely. Fixed
  (now checks `aws_role_arn`), verified against the **real live Supabase DB** via a
  direct read-only call (not just re-reading the code), and a new
  `tests/integration/test_crud.py` added for regression coverage (correctly skips
  here — no local disposable test Postgres in this sandbox; do **not** point
  `TEST_DATABASE_URL` at the real Supabase instance, `conftest.py`'s `db_session`
  fixture does `create_all`/`drop_all` around every test and would wipe it).
- Tests: `test_aws_role.py` (8 — mocked STS: params, caching, expiry-refresh,
  per-key cache isolation, error propagation), `test_user_aws.py` (3),
  `tests/integration/test_settings_endpoint.py` rewritten for the role/external_id
  flow (skips here, no local test DB). Full suite: **187 passed, 29 skipped.**
- **Rebuilt and verified against the real running stack**: schema change confirmed
  live, `crud.py` fix confirmed against the real DB, backend/frontend both rebuilt
  and healthy, CFN template confirmed downloadable at `/nimbus-cross-account-role.yaml`.

**Known, honest limit — cannot be verified from this session:** a real
cross-account `AssumeRole` end-to-end (deploy the CFN stack in a *second*, separate
AWS account, paste the Role ARN into Settings, confirm Nimbus can actually act on
that second account) needs two distinct AWS accounts. Everything above is verified
as far as mocked-STS unit tests + the real single-account plumbing (schema, live
DB, service identity, template structure) can go; the actual cross-account trust
handshake is the one thing only a real second account can prove. Try this next.

## DEV-5 — Chat UI overhaul: resource map, session switcher, model selector — DONE (2026-07-05)

Replaced the chat page's Editor + Terminal panels with a live Resource Map, added a
session switcher (top 5 recent + "All sessions" modal) and a model/provider
selector. Also closed out a plan from an earlier session: gutted
`routes/workspace.py` now that nothing needs it.

**Why `routes/workspace.py` was safe to delete entirely, not just partially:**
It held subprocess `exec` (a real attack surface), GitHub clone-via-subprocess, and
file read/write — all against a **process-global, non-per-user** `_workspace` dict
(the same class of bug fixed elsewhere this session for Bodyguard/AWS creds, never
fixed here because the whole feature is gone now). Traced every consumer first:
only the now-deleted `EditorPanel`/`TerminalPanel` called it. The one path that
looked load-bearing — `chat.py`'s `_finalize_turn` writing generated files to that
temp dir — turned out to be dead code: the frontend's `FilesCard` downloads
`generated_files` directly from the JSON response via a Blob, and `GET
/api/files/{session_id}` reads `session.generated_files` (a DB column) directly.
Nothing ever read the temp-dir copy back. Confirmed via `grep` before deleting, not
assumed. The standalone `/terminal` and `/dashboard` pages (pre-existing, found via
a build-output check after an earlier `Glob` call gave a false negative) only ever
called `/api/dashboard*`, never `/api/workspace/*` — unaffected.

**What was built:**
- **`db/models.py` / migration `5567ba294299`** — new `Session.ui_messages` (JSONB):
  the frontend's *rendered* message shape (role, content, plan, execution_results,
  generated_files, timestamp), distinct from `history` (the raw agent-loop format
  the LLM providers consume). Without this, "switch to a past session" could only
  ever resume the underlying agent context blind — it couldn't re-render the old
  plan cards/results, since those were never persisted in UI-shape before. Applied
  to the real live Supabase DB (verified via `information_schema.columns`).
- **`routes/chat.py`** — auto-titles a new session from its first message
  (whitespace-collapsed, 60 chars); `_append_ui_messages()` mirrors exactly what the
  frontend renders into `ui_messages` each turn (translating `confirm=True/False`
  into the same "Yes, deploy"/"No, cancel" display text the frontend already used,
  so a reloaded session reads identically to a live one); `ChatRequest.provider`
  passes through to `PipelineState.provider` (which — already fully wired through
  every agent call in `orchestrator.py` from DEV-2 — needed zero orchestrator
  changes, just this one route-level gap closed); unknown provider values fall back
  to the env default instead of erroring, since the frontend only ever sends known
  values anyway. `session.model` now stores the provider slug used to start that
  session (e.g. `"groq"`), for display in the session list — nothing else depended
  on its previous exact-model-id format (checked via grep).
- **`routes/sessions.py`** (new) — `GET /api/sessions` (list, owned, ordered by
  `updated_at` desc) and `GET /api/sessions/{id}` (detail incl. `ui_messages`).
- **Frontend (`chat/page.tsx`)** — `ResourceMap` (polls `/api/dashboard` every 8s,
  grouped by resource type, with a Bodyguard status chip) replaces Editor+Terminal
  in the right panel, now Activity 40% / Resource Map 60%. `SessionSwitcher` (top 5
  + "New chat" + "All sessions" modal) and `ModelSelector` (provider dropdown,
  persisted to `localStorage`) sit in a new top bar below the navbar. Selecting a
  session fetches `ui_messages` and loads them directly into `messages` state — no
  transform needed, since the backend shape was designed to match the frontend's
  `Message` interface exactly.
- **Test infra fix (found by actually running the suite against a real DB, not just
  trusting the skip):** `pytest.ini` had no `asyncio_default_fixture_loop_scope`,
  so pytest-asyncio defaulted to a new event loop **per test function**, while
  `db/engine.py`'s `engine` is a module-level singleton created once — asyncpg
  connections got bound to a dead event loop between tests, corrupting every
  `requires_db` test with "another operation is in progress" / "attached to a
  different loop" errors. This was **invisible in every prior session** because
  `DB_AVAILABLE` was always `False` (no reachable test Postgres), so 100% of
  `requires_db` tests silently skipped and this never ran for real. Fixed by
  setting both `asyncio_default_fixture_loop_scope = session` and
  `asyncio_default_test_loop_scope = session`. Verified by spinning up a disposable
  local `postgres:16` container (not the real Supabase — that fixture does
  `create_all`/`drop_all` per test, which would have wiped the live DB) and running
  the full suite against it: went from 33 errors → 2 failures → 0. The final 2 were
  pre-existing latent bugs in `test_chat_endpoint.py` (asserting the pre-cost-
  enrichment `plan` dict against the post-`finalize_node` one, which adds
  `estimated_monthly_cost`/`cost_breakdown`) — fixed alongside, also never caught
  before for the same always-skipped reason.
- Tests: `test_chat_endpoint.py` (+7: auto-title, ui_messages shape, provider
  passthrough/fallback, confirm-text mapping, file-delivery regression),
  `test_sessions_endpoint.py` (new, 6: list/detail/ownership-scoping/404s),
  `test_crud.py` (3, from the STS work). **Full suite: 222/222 passed against a
  real disposable Postgres** — the strongest verification this project has had, not
  just "skipped cleanly."
- Frontend: `npx tsc --noEmit` clean, `npm run build` (production build) succeeds.

**What still needs a real browser (not verifiable headlessly):** Clerk's dev
instance requires a browser-JS "dev browser" JWT handshake before protected routes
render — curl gets a 404 (`x-clerk-auth-reason: dev-browser-missing`) regardless of
whether the page actually works, so this doesn't distinguish a real bug from
expected behavior. `/browse` (referenced in this machine's global CLAUDE.md) wasn't
actually available as an installed skill in this session, so an automated headless
check wasn't possible either. Backend is verified as thoroughly as this session
allows (222/222 real-DB tests, clean logs, healthy containers); the actual rendered
UI — layout, session switching, model selector, resource map live-updating — needs
you to open `/chat` in a real browser next.

## Other unblocked tracks
With Bodyguard multi-tenant-safe, **SEC-2** (rate limiting) and **PROD-4**
(Kubernetes) remain unblocked if priorities shift away from the pipeline work.

## Tooling note — gstack skills
Only the single `gstack` skill (browser/QA, i.e. `/browse`) is actually discoverable by
Claude Code right now. The other ~30 gstack skills (`plan-eng-review`, `cso`,
`office-hours`, etc.) are fully built with proper SKILL.md frontmatter, but live one
directory too deep at `~/.claude/skills/gstack/<name>/SKILL.md` instead of
`~/.claude/skills/<name>/SKILL.md`, so Claude Code's one-level-deep skill scan never
finds them. Until that's fixed (flatten/symlink each into `~/.claude/skills/` directly),
those are user-typed slash commands only — Claude can't invoke them via the Skill tool.
