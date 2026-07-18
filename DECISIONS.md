# Nimbus — Decisions & Open Work

Cross-machine continuity doc. The conversation transcript and file-based memory
are local to the machine that made them and do **not** travel with the repo —
this file does. It holds only what the code and `git log` **cannot** tell you:
the *why* behind non-obvious decisions, and the work that is genuinely still
open. It is deliberately not a changelog — for "what shipped and how," read the
code and `git log`. A full historical narrative through 2026-07-18 is archived
at `docs/archive/HANDOFF-2026-07-18.md`.

**Repo:** github.com/SirCartier50/nimbus · **Stack:** FastAPI backend +
Next.js 16 / React 19 / TS frontend · Postgres (Supabase) · Clerk auth · boto3.

---

## What Nimbus is

Agentic AWS management: users describe infrastructure in plain English; AI agents
(Requirements, Architect, Executor + deterministic Validator/Cost/Bodyguard)
plan, deploy, and monitor it. Originally a Nova hackathon build; goal now is
production-ready and publicly deployable.

---

## Decisions that the code won't explain (the *why*)

**Deploy target (2026-07-15).** Backend on free-tier EC2 + `docker compose` +
Caddy reverse proxy; frontend on Vercel free tier. K8s explicitly rejected for
now: single-node k3s doesn't fit 1 GB free-tier RAM, gives zero extra
survivability over compose restart policies on one machine, and Caddy covers the
ingress/reverse-proxy/request-control it was wanted for. Same images migrate to
ECS/EKS when traffic justifies multi-node. Honest availability limit: survives
crashes + auto-recovery, **not** machine death / AZ outage. See `infra/DEPLOY.md`.

**AWS access via STS AssumeRole, not stored keys (2026-07-04).** Full cutover, no
legacy access-key path — done pre-launch specifically so there are zero real
users' stored keys to migrate later. `UserSettings` holds `aws_role_arn` +
`aws_external_id` (neither Fernet-encrypted: an ARN is an identifier, an
external_id only needs to be unique, not secret). `utils/crypto.py`/Fernet are
gone. Nimbus's own service identity is IAM user
`arn:aws:iam::804306814230:user/botouser`. **Unverified:** a real cross-account
handshake needs a *second* AWS account — only single-account plumbing is proven.

**Agent tools: curated + generic hybrid, NOT one generic blob (DEV-4).** User
explicitly rejected the generic `create_resource(type, config)` design mid-build
("provide the model with every type of tool… an interface for the model to use
boto3"). Shipped: 15 botocore-sourced per-resource `create_*` tools
(`providers/aws_registry.py`) giving real field names/enums, **plus** a generic
Cloud Control path (`providers/cloud_control.py`, `AWS::Service::Resource`) for
the long tail. Curated = precise cost + special actions (stop/start EC2,
empty-then-delete S3, Lambda-role bootstrap); generic = breadth. The executor
already serves **both** tool sets live (`use_cloud_control=True`); the Architect
already emits either form.

The curated-vs-generic preference is a config knob:
`ARCHITECT_RESOURCE_PREFERENCE` = `curated` (default) | `balanced` | `generic`
(`agents/architect.py`). As models improve, `generic` lets the product cover all
of AWS without growing the registry — but **flip it only on eval evidence**
(`backend/evals/CHECKLIST.md`), never blindly: the curated tools carry real
non-model value (cost, free-tier enforcement, special actions) a flip must not
lose. Don't grow the registry.

**Server-side schema validation before boto3.** Models hallucinate AMI IDs / param
names, so every create config is `jsonschema`-validated against the
full-fidelity botocore schema before the call. Botocore is the source of truth —
keep this as a cheap ground-truth check; do **not** hand-author validation rules.
The executor already feeds real boto3/validation errors back to the model as a
retry loop (tool-loop error results + `EXECUTOR_PROMPT` rule 2); validation
failures are collapsed to a concise field+reason message
(`_concise_validation_error`) so the retry signal is actionable, not a schema dump.

**Pipeline is intentionally multi-agent (see `PIPELINE_PLAN.md`, authoritative).**
Executor stays an LLM agent (not plain code); the critic is split into a
deterministic Tier-1 refine loop (`pipeline/validation.py`, no false positives,
`MAX_VALIDATION_ROUNDS=4` backstop) + a single advisory Tier-2 LLM pass
(`agents/critic.py`) the **user** adjudicates. Agents are `(state)->state`
functions; orchestration is a real LangGraph `StateGraph` with a
`validate→architect→validate` refinement cycle and `stream_turn()` SSE progress.

**Bodyguard is deterministic plain code, not an LLM (2026-07-15).** It ran a
Bedrock tool-loop per connected user every 5 min 24/7 → surprise bill. Rewritten
to identical decision rules in plain Python (`agents/bodyguard.py`), state
persisted to Postgres (`bodyguard_alerts/logs/status`), extracted to a
single-replica `worker.py`. Correctly scoped: fixed rules, zero judgment upside —
do not put an LLM back here.

**LLM providers (2026-07-15).** Default `openrouter` everywhere. Bedrock removed
and no longer user-selectable (class kept for tests only). Only
`OPENROUTER_API_KEY` exists in `backend/.env` — Groq/HF selector entries error
with a clear message until keys are added. **Rules:** live-model verification uses
FREE providers only (Groq/OpenRouter/HF), never frontier/Bedrock; only smart 70B+
tool-capable models in the product selector. The provider abstraction is a thin
one-method (`infer()`) interface; default model IDs are centralized in
`config.MODEL_DEFAULTS` (one edit per model drop, each overridable via
`<PROVIDER>_MODEL`). When a new model appears, run `backend/evals` against it
before making it the default (see `backend/evals/CHECKLIST.md`).

**Clerk auth is hand-rolled PyJWT + JWKS (RS256), deliberately not the SDK
(2026-07-04).** Clerk's own guide recommends exactly JWKS+PyJWT for non-JS
backends, and the Python SDK's request-adapter contract was inconsistent between
two official docs. For the app's auth gate, an unverifiable adapter for zero gain
was the wrong risk. `require_plan`/`require_feature` deps exist and are tested but
are **not attached to any route** — no gating rule has been decided yet.

**Chat page: Editor + Terminal panels removed; `routes/workspace.py` deleted.**
They wrapped subprocess exec + temp-file + GitHub-clone over a process-global
non-per-user dict — a real attack surface with little value (configs download
directly from the chat). Right panel is Activity + live Resource Map.

**DB.** Supabase Postgres, SQLAlchemy 2.0 async (asyncpg) + Alembic. `Session`
has both `history` (raw agent-loop format the LLM consumes) and `ui_messages`
(rendered frontend shape) — a reloaded session must re-render plan cards/results,
which the raw history can't do. Dashboard resources are pulled live from boto3
(Redis-cached), never persisted. Context-window trimming is a post-launch concern.

---

## Genuinely open work (not derivable from code)

**Highest-value UX (from the user's own 2026-07-15 e2e testing):**
- **E2E-1** Token-stream assistant replies word-by-word (biggest complaint —
  replies feel interminable).
- **E2E-4** Real costs via Cost Explorer (dashboard hardcodes $0 free-tier notes;
  console shows ~$1 July incl. S3).
- **E2E-6** Resource detail view (click resource → console-style info/logs +
  start/stop + guarded delete). Note: only EC2/S3/DynamoDB/Lambda are listed today
  — a deploy created an API Gateway the dashboard can't even display.

**UI/UX debt:** UX-2 markdown rendering of assistant replies (renders raw today) ·
UX-3 decide `/terminal`'s fate (orphaned, duplicates dashboard Bodyguard panel) ·
UX-4 surface-hierarchy + type-scale pass (every card is the same flat `.glass`;
also in `CLAUDE.md`) · UX-5 persist error/failed turns to `ui_messages`.

**Testing:** TEST-7 — Playwright e2e infra exists (`frontend/e2e/`, real
authenticated session via `@clerk/testing`) but only covers page reachability.
Highest-value next slice: the chat turn flow (send → plan → confirm/cancel →
execution) and SSE stream parsing. *Prereq already done:* Clerk "Client Trust"
(new-device email verification) was disabled in Dashboard → Attack protection for
automated sign-in — don't re-enable without updating the e2e auth flow.

**Deploy (PROD-4) — code/docs done, remaining steps are USER actions:** launch the
EC2 box + DNS + repo secrets (`DEPLOY_HOST/USER/SSH_KEY`) per `infra/DEPLOY.md`,
import the repo into Vercel. Re-measure the k6 baseline on the real EC2 box.

**Billing — blocked on a business decision, not code:** only a "Free" plan exists
in Clerk, so the billing page reads as unfinished. Someone must define the paid
tier slugs + what each gates in Clerk Dashboard → Billing before
`require_plan`/`require_feature` can be attached to routes.

---

## Gotchas that will bite you

- **Docker serves stale code on `up` alone.** Use `docker compose build && docker
  compose up -d`.
- **Secrets are gitignored.** Recreate `.env`, `backend/.env`,
  `frontend/.env.local` from their `.example` templates on a new machine. Root
  `nimbus/.env` (not `frontend/.env`) feeds the Clerk build args in compose.
- **Never point `TEST_DATABASE_URL` at the real Supabase DB** — `conftest.py`'s
  `db_session` fixture does `create_all`/`drop_all` per test and will wipe it. Use
  a disposable local `postgres:16` container.
- **CI runs the integration tests that always skip locally** (no local Postgres) —
  a green local run is not a green CI run.
