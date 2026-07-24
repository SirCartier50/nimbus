# Attack surface — running inventory

Living map of everything Nimbus has deployed across hosts, vendors, and
technologies, and the total exposure of each. This is a **continuously-updated
resource**: it is maintained by the `attack-surface` skill (refresh/extend the
inventory) and each entry is deep-assessed by the `assess-attack-surface`
workflow (which also sets a testing cadence). Keep it grounded in the code and
real config — every claim here should be verifiable in the repo, not assumed.

- **Last verified:** 2026-07-19 (against the repo at branch `harness/bitter-lesson-tier1`)
- **Scope:** the Nimbus product. Add other projects as new top-level systems.

## Legend

**Type:** `web` (browser-facing UI) · `api` (programmatic) · `db` (datastore) ·
`infra` (host/platform) · `identity` (auth/secret) · `pipeline` (CI/CD).

**Exposure (audience):** `PUBLIC` (open internet) · `TOKEN` (bearer/JWT
required) · `OAUTH` (identity-provider login) · `INTERNAL` (private network only)
· `OUTBOUND` (we call it; it doesn't call us) · `KEY` (long-lived secret/key).

**Criticality** = blast radius if compromised (C1 catastrophic → C4 minor).

## Summary

| # | System | Type | Hosting | Exposure | Criticality |
|---|--------|------|---------|----------|-------------|
| 1 | Vercel — frontend | web | 3rd-party PaaS | PUBLIC | C3 |
| 2 | EC2 production box | infra | AWS IaaS (self-managed) | PUBLIC (80/443), KEY (SSH) | C1 |
| 3 | Nimbus Backend API (FastAPI) | api | self-hosted on #2 | PUBLIC + TOKEN (JWT) | C1 |
| 4 | Clerk — auth IdP | identity | 3rd-party | PUBLIC + OAUTH | C1 |
| 5 | Supabase — Postgres | db | 3rd-party managed | INTERNAL-over-internet + KEY | C1 |
| 6 | AWS cross-account role (per user) | api/infra | user accounts, via STS | KEY (AssumeRole + ExternalId) | C1 |
| 7 | `botouser` — Nimbus AWS identity | identity | AWS IAM | KEY (long-lived) | C1 |
| 8 | GitHub — repo + Actions CI/CD | pipeline | 3rd-party | OAUTH + KEY (secrets) | C2 |
| 9 | Redis | db | self-hosted on #2 | INTERNAL | C2 |
| 10 | LLM providers (OpenRouter/Groq/HF) | api | 3rd-party | OUTBOUND + KEY | C3 |
| 11 | Sentry (optional) | api | 3rd-party | OUTBOUND + KEY | C4 |
| 12 | Load-test / token-mint tooling | pipeline | local/CI | KEY (mints JWTs) | C3 |

**Crown jewels (single secrets with the widest blast radius):** the `botouser`
AWS access key (#7 — reaches *every* connected user account), the Supabase
`DATABASE_URL` password (#5 — all user data), the Clerk secret key (#4 — mint
any session), and `DEPLOY_SSH_KEY` (#8/#2 — own the prod box). All four live in
`backend/.env` on the EC2 box or in GitHub Actions secrets.

---

## 1. Vercel — frontend

- **Tech:** Next.js 16 (App Router), React 19, TypeScript, Tailwind v4,
  `@clerk/nextjs`, `framer-motion`, `@phosphor-icons/react`.
- **Self/third-party:** third-party PaaS (Vercel free tier). Builds from GitHub.
- **What's deployed:** the whole dashboard UI (`/login`, `/signup`, `/dashboard`,
  marketing/hero). `NEXT_PUBLIC_*` config baked at build (API URL, Clerk
  publishable key, Clerk route URLs). `CLERK_SECRET_KEY` injected at runtime.
- **Type:** web property (public).
- **Auth into the platform:** Vercel account (GitHub OAuth). Deploy = git push.
- **Auth of the app itself:** Clerk (OAuth/JWT); unauthenticated users see only
  marketing + login.
- **Defenses:** Vercel-managed TLS; Clerk gates app routes; secrets kept out of
  `NEXT_PUBLIC_*` (only the publishable key, which is public by design).
- **Exposure:** `PUBLIC`. Login via `OAUTH` (Clerk).
- **Common misconfigs to test:** a real secret accidentally in a `NEXT_PUBLIC_*`
  var; preview deployments publicly reachable without auth; missing security
  headers (CSP, HSTS) on the Vercel side; SSRF/secret-leak from any route
  handlers/server actions; stale prod using Clerk **test** keys.

## 2. EC2 production box

- **Tech:** single free-tier EC2 (Ubuntu AMI), Docker + Docker Compose
  (`docker-compose.prod.yml`): Caddy 2, backend, Bodyguard worker, Redis.
- **Self/third-party:** self-managed host on AWS IaaS.
- **What's deployed:** Caddy (only host listener, 80/443, terminates TLS,
  Let's Encrypt auto-cert, reverse-proxies to `backend:8000`); backend API;
  worker; Redis. `/opt/nimbus` working tree; `backend/.env` with all secrets.
- **Type:** infra.
- **Auth into it:** SSH key (`DEPLOY_SSH_KEY`, user `ubuntu`). No console/password.
- **Defenses:** backend/redis have **no host ports** (compose-network only);
  Caddy adds HSTS, `X-Content-Type-Options`, `Referrer-Policy`, strips `Server`;
  `/metrics` returns 403 at the proxy; `restart: unless-stopped` + EC2
  auto-recovery.
- **Exposure:** `PUBLIC` on 80/443; SSH via `KEY`. Redis/backend `INTERNAL`.
- **Common misconfigs to test:** security-group SSH open to `0.0.0.0/0` instead
  of a known IP; SG exposing 8000/6379 directly; Docker socket exposed; OS/
  package patch level; no fail2ban / no SSH rate-limit; single instance = no HA
  (accepted, see `infra/DEPLOY.md`); IMDSv1 enabled (SSRF → instance role creds).

## 3. Nimbus Backend API (FastAPI)

- **Tech:** FastAPI + Uvicorn, SQLAlchemy async + asyncpg, Alembic, LangGraph
  agent pipeline, Redis, `prometheus-client`, `sentry-sdk`, PyJWT.
- **Self/third-party:** self-hosted (on #2). Also runnable via `docker-compose.yml`.
- **What's deployed / routes:** `/api/chat`, `/api/dashboard`, `/api/sessions`,
  `/api/settings` (all behind auth); unauthenticated `/health`, `/health/ready`,
  `/metrics`. The agent pipeline drives **mutating AWS calls on user accounts**
  (see #6) — the highest-value capability here.
- **Type:** api.
- **Auth into it:** Clerk JWT via JWKS (`auth.py`: `PyJWKClient`, RS256, issuer +
  audience verified) as HTTP middleware on all `/api/*`. Maps `clerk_user_id` →
  internal user.
- **Defenses:** JWT middleware; Redis-backed rate limiting (`ratelimit.py`,
  per-user token buckets) + `DAILY_TURN_LIMIT`; CORS **allowlist** (not `*`) with
  credentials; request-id + Prometheus observability on every request incl.
  rejects; **prompt-injection defenses** (`docs/security/prompt-injection.md`:
  plan-subset invariant, managed-only mutations, tool-output spotlighting,
  heuristic injection guard, exfil-intent advisories).
- **Exposure:** `PUBLIC` endpoint; `/api/*` requires `TOKEN` (Clerk JWT/OAuth).
- **Common misconfigs to test:** `/metrics` reachable if the proxy rule is
  dropped (info leak); CORS origin list too broad; JWT audience/issuer not
  enforced (verify `auth.py` options); IDOR across `user_id` on
  sessions/dashboard; SSRF from the agent's AWS/tool calls; rate-limit bypass;
  the STS blast radius (#6/#7); missing authz on any newly-added route.

## 4. Clerk — authentication IdP

- **Tech:** Clerk (hosted auth). Frontend `@clerk/nextjs` + `@clerk/themes`;
  backend verifies JWTs against Clerk JWKS.
- **Self/third-party:** third-party.
- **What's deployed there:** user accounts, sessions, sign-in/up flows, JWT
  templates, `CLERK_ISSUER` (`https://<app>.clerk.accounts.dev`).
- **Type:** identity (web login + JWKS API).
- **Auth into the platform:** Clerk dashboard account.
- **Keys:** publishable `pk_*` (public, in frontend), secret `sk_*` (server-only,
  runtime env). `.env.example` ships `pk_test_*`/`sk_test_*` placeholders —
  **confirm prod uses live keys**.
- **Defenses:** asymmetric JWT (JWKS rotation), server holds only the secret key,
  test/live key separation.
- **Exposure:** `PUBLIC` (login pages) + `OAUTH`/JWT issuance.
- **Common misconfigs to test:** **test keys in production**; leaked secret key;
  overly long session/JWT TTL; missing/unused webhook signature verification if
  webhooks get added (none today); permissive allowed redirect/origin config;
  JWT `aud` not scoped.

## 5. Supabase — Postgres

- **Tech:** Postgres 16, reached via `postgresql+asyncpg` through the **Session
  Pooler** (`aws-1-...pooler.supabase.com:5432`).
- **Self/third-party:** third-party managed DB.
- **What's deployed there:** the app schema via Alembic — `users`
  (`clerk_user_id` unique), sessions, plans/deployments, chat history, etc.
- **Type:** db.
- **Auth into it:** `DATABASE_URL` with `postgres.<project-ref>:<password>`.
- **Defenses:** credential in a gitignored secret; TLS to the pooler; app-level
  authz (every request resolves `clerk_user_id`→user in `db/crud.py`).
- **Exposure:** logically `INTERNAL` (backend only) **but reachable over the
  public internet with the password** — not VPN/private-network isolated. Access
  gate is the `KEY`.
- **Common misconfigs to test:** DB credentials leaking (logs, error traces,
  client bundles); no IP allowlist on Supabase; use of the `service_role` key;
  **no row-level security** (authz is app-side only — a query missing its
  `user_id` filter = cross-tenant read); pooler/direct host publicly open;
  **never** point `TEST_DATABASE_URL` at this DB (the test fixture `create_all`/
  `drop_all` wipes it — see project memory).

## 6. AWS cross-account role (per user account)

- **Tech:** STS `AssumeRole` into `NimbusAccessRole` in each user's account
  (`infra/nimbus-cross-account-role.yaml`); boto3 with short-lived creds
  (`utils/aws_role.py`). Provisions ~15 curated services + generic Cloud Control.
- **Self/third-party:** runs against the **user's** AWS account.
- **What's deployed there:** whatever the agent creates, all tagged
  `ManagedBy=Nimbus` (EC2, S3, RDS, Lambda, VPC, etc.).
- **Type:** api / infra.
- **Auth into it:** `sts:AssumeRole` restricted to `botouser` (#7) **and** a
  per-connection `ExternalId` (confused-deputy protection). `MaxSessionDuration`
  3600s.
- **Defenses:** ExternalId; **least-privilege role template** (P0-2 — scoped
  inline policy is now the default; PowerUser is opt-in); `ManagedBy=Nimbus`
  tagging; executor **plan-subset** + **managed-only** invariants; Bodyguard only
  *stops* (reversible), never terminates.
- **Exposure:** `KEY` — assumable only with botouser creds + ExternalId.
- **Common misconfigs to test:** role still on `PowerUserAccess` (pre-P0-2
  stacks); trust policy missing the ExternalId condition; ExternalId guessable/
  reused across users; overly broad scoped policy; a resource left untagged
  escaping managed-only checks.

## 7. `botouser` — Nimbus's own AWS identity

- **Tech:** IAM user with long-lived access keys (`AWS_ACCESS_KEY_ID` /
  `AWS_SECRET_ACCESS_KEY` in `backend/.env`). The principal that assumes every
  user role (#6).
- **Self/third-party:** self (AWS IAM).
- **Type:** identity.
- **Auth into it:** the long-lived key pair.
- **Defenses:** `.env` gitignored, lives only on the EC2 box; ExternalId means a
  stolen key alone still needs each user's ExternalId to assume their role.
- **Exposure:** `KEY`. **Highest blast radius on the board** — this key is the
  single principal trusted by every connected account.
- **Common misconfigs to test:** key on disk with no rotation; botouser holding
  more than `sts:AssumeRole` (should be minimal — verify its own policy); no
  CloudTrail/alerting on its use; key ever echoed into logs/Sentry; consider
  migrating to instance-role + IMDSv2 to remove the static key.

## 8. GitHub — repo + Actions CI/CD

- **Tech:** GitHub repo; Actions `ci.yml` (Postgres 16 + Redis services, backend
  tests, `next build`) and `deploy.yml` (SSH deploy via `appleboy/ssh-action`).
- **Self/third-party:** third-party.
- **What's deployed there:** source, workflows, and repo **secrets**:
  `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (and any Clerk/AWS build secrets).
- **Type:** pipeline (+ web/API).
- **Auth into it:** GitHub account (OAuth), SSH/PAT for git.
- **Defenses:** deploy gated on green CI; single-flight deploy concurrency;
  deploy only from `main`; CI uses a dummy Clerk key for prerender.
- **Exposure:** `OAUTH` (accounts) + `KEY` (Actions secrets).
- **Common misconfigs to test:** `pull_request`-triggered CI running untrusted
  code with access to secrets (pwn-request) — CI here runs on PRs, so confirm no
  secrets are exposed to fork PRs; third-party action pinned to a **tag**
  (`appleboy/ssh-action@v1.2.0`) not a commit SHA (supply-chain risk); branch
  protection on `main`; `GITHUB_TOKEN` permissions; repo visibility (private?);
  secret scanning / Dependabot enabled.

## 9. Redis

- **Tech:** `redis:7-alpine`, `--maxmemory 64mb --maxmemory-policy allkeys-lru`.
- **Self/third-party:** self-hosted container on #2.
- **What's deployed there:** rate-limit token buckets, **STS-credential cache**,
  dashboard cache — all reconstructible.
- **Type:** db/cache.
- **Auth into it:** none (no password) — relies on network isolation.
- **Defenses:** no host port (compose-network only); bounded memory + LRU.
- **Exposure:** `INTERNAL`.
- **Common misconfigs to test:** ever binding 6379 to the host / SG opening it →
  unauthenticated access; it caches STS creds, so a container escape or a
  misexposed port leaks live cloud credentials; add a password + TLS if it ever
  leaves the single-host network.

## 10. LLM providers — OpenRouter / Groq / HuggingFace

- **Tech:** OpenAI-compatible APIs (`openai` SDK). Default OpenRouter
  (`meta-llama/llama-3.3-70b-instruct`); Groq (`llama-3.3-70b-versatile`); HF
  (`deepseek-ai/DeepSeek-V3-0324`). Tool-calling required.
- **Self/third-party:** third-party. **Free tiers only** (project policy: never
  Bedrock/frontier for the product).
- **Type:** api (outbound).
- **Auth into it:** API keys (`OPENROUTER_API_KEY` / `GROQ_API_KEY` / `HF_TOKEN`).
- **Defenses:** keys in gitignored `.env`; prompt-injection handling on their
  outputs (treated as untrusted, spotlighted, plus deterministic invariants).
- **Exposure:** `OUTBOUND` + `KEY`.
- **Common misconfigs to test:** key leak → billing/quota abuse; sensitive user
  data (AWS resource details) sent to a third party — confirm what leaves the
  box; response-driven prompt injection (covered by #3 defenses); no egress
  allowlist from the EC2 box.

## 11. Sentry (optional)

- **Tech:** `sentry-sdk`, enabled only when `SENTRY_DSN` is set (off by default).
- **Type:** api (outbound error tracking).
- **Auth:** DSN (semi-public ingest key).
- **Exposure:** `OUTBOUND` + `KEY`.
- **Common misconfigs to test:** secrets/PII captured in breadcrumbs, request
  bodies, or exception context; DSN with an over-broad scope; environment/PII
  scrubbing not configured.

## 12. Load-test / token-mint tooling

- **Tech:** `loadtest/` — k6 scenarios, `mock_llm.py`, `gen_tokens.py` (mints
  JWTs), `docker-compose.loadtest.yml`. `out/` is gitignored.
- **Type:** pipeline (local/CI only — not a production surface).
- **Exposure:** `KEY` — it can mint auth tokens.
- **Common misconfigs to test:** minted tokens committed to git (must stay
  gitignored); a load-test token valid against a real environment; the mock LLM
  or test tokens shipped in a prod image.

---

## Open gaps / to verify on next pass

- Confirm production Clerk keys are **live**, not `*_test_*`.
- Confirm the EC2 security group restricts SSH and exposes only 80/443.
- Confirm IMDSv2-only on the EC2 instance (blocks SSRF→role-cred theft).
- Confirm `botouser`'s own IAM policy is minimal (ideally just `sts:AssumeRole`).
- Decide whether Supabase gets an IP allowlist and/or RLS as defense-in-depth.
- Re-run P0-2: are any already-deployed user role stacks still on PowerUserAccess?

## Maintenance

Run `attack-surface` to re-verify and extend this file (it re-derives each entry
from the current repo and flags drift). Run `assess-attack-surface <system>` to
deep-test one entry and (re)set its testing cadence. Update **Last verified**
whenever either runs.
