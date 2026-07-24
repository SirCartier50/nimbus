---
name: attack-surface
description: >
  Maintain the running attack-surface inventory at docs/security/attacksurface.md.
  Use when asked to build, refresh, verify, or extend the attack surface / asset
  inventory — "update the attack surface", "what are we exposed on", "add <system>
  to the attack surface", "check attacksurface.md for drift". Re-derives every
  entry from the current repo/config so the file stays true, and flags drift
  between what's documented and what's actually deployed.
---

# Attack surface — inventory maintainer

You keep `docs/security/attacksurface.md` an accurate, evidence-based map of
everything deployed. The cardinal rule: **every claim is verified against the
repo/config, never asserted from memory.** A confident-but-wrong inventory is
worse than none — it hides real exposure.

## When invoked

1. **Read the current file** (`docs/security/attacksurface.md`) if it exists.
2. **Re-discover the surface from ground truth** (see checklist below). Diff what
   you find against what the file says.
3. **Report drift** before rewriting: list entries that changed, new systems
   found, and documented systems no longer present. If nothing changed, say so
   and just bump *Last verified*.
4. **Update the file** in place, preserving the schema and ordering. Bump
   `Last verified` to today and note the branch/commit you verified against.

## Discovery checklist (ground-truth sources)

Sweep these; each reveals systems, tech, secrets, and exposure:

- **Deploy/infra:** `docker-compose*.yml`, `infra/` (`Caddyfile`, `DEPLOY.md`,
  CloudFormation/Terraform), any reverse-proxy or ingress config. → hosts,
  listeners, ports, TLS, what's host-exposed vs network-internal.
- **CI/CD:** `.github/workflows/*` → pipeline, deploy path, **repo secrets** by
  name, third-party actions (and whether pinned to a SHA), PR-trigger exposure.
- **Secrets/config surface:** every `.env.example` (never read a real `.env`
  aloud or echo secret values) → each vendor, each key, each connection string.
  The set of secret *names* is the crown-jewel list.
- **Dependencies:** `requirements.txt` / `package.json` → auth libs, DB drivers,
  observability SDKs, cloud SDKs → which vendors are actually wired in.
- **App entrypoints & auth:** the API's `main.py`/router registration, auth
  middleware, CORS, rate limiting, health/metrics endpoints → which routes are
  public vs token-gated, and how tokens are verified.
- **Data layer:** migrations/schema, ORM/CRUD → the database, its tables, and
  whether authz is app-level or RLS.
- **Outbound integrations:** provider clients (LLM, email, error tracking,
  payments) → third-party APIs we call and the keys they need.
- **Docs of record:** `DECISIONS.md`, `README.md`, architecture/handoff docs →
  deploy target, deliberate tradeoffs, known debt.

For a multi-project surface, repeat per repo/project and add each as a new
top-level system; keep this file the union.

## Per-entry schema (keep it consistent)

For every system record all of: **Tech**; **Self vs third-party**; **What's
deployed there**; **Type** (web/api/db/infra/identity/pipeline); **Auth into it**;
**Defenses** (security mechanisms in place); **Exposure** per audience using the
legend (PUBLIC / TOKEN / OAUTH / INTERNAL / OUTBOUND / KEY); **Criticality**
(C1–C4 by blast radius); **Common misconfigs to test** (platform-specific — the
concrete things `assess-attack-surface` will check).

Maintain the **Summary table**, the **Crown jewels** callout (widest-blast-radius
secrets), and the **Open gaps / to verify** list. Mark anything you couldn't
confirm as `verify` rather than stating it as fact.

## Drift signals to always check

- A secret name in a workflow/`.env.example` with **no** matching system entry.
- A compose service, port, or route not reflected in any entry's Exposure.
- A dependency implying a vendor (e.g. `stripe`, `sentry-sdk`) with no entry.
- An entry whose Defenses claim a control the code no longer implements.
- Exposure that widened (a new public route, a newly host-bound port).

## Guardrails

- Read-only discovery + editing one doc = act autonomously, then report.
- Never print real secret values; reference them by name/location only.
- Don't scan or probe external hosts here — that's `assess-attack-surface`, and
  only against systems the user owns/authorizes.
- Keep it honest: unknowns are `verify`, not confident prose.
