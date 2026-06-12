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
- [ ] **SEC-3** Encrypt stored AWS credentials (Fernet) — depends on DB

Development:
- [ ] **DEV-1** Finish in-progress refactor — stabilize tool_use.py integration (mostly done; commit/verify)
- [ ] **DEV-2** Replace Amazon Nova with a free/open LLM
- [ ] **DEV-3** Add database — persist chat sessions, user configs, deployment history (IN PROGRESS)
- [ ] **DEV-4** Expand agent tool coverage — full AWS API access (this is the config-driven refactor)
- [ ] **DEV-5** Improve UI — chat, dashboard, terminal, editor (remove editor/terminal, add resource map)

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

## Immediate Next Step When Resuming
Continue **DEV-3**: finish the schema, write SQLAlchemy models, create the first Alembic
migration, then swap the in-memory `_sessions` dict in `routes/chat.py` for DB-backed
persistence. User wants to do most of this themselves to learn — guide, don't auto-implement.
