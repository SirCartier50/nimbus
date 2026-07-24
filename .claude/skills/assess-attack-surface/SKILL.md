---
name: assess-attack-surface
description: >
  Thoroughly and efficiently assess one attack surface (a system from
  docs/security/attacksurface.md) and recommend a testing frequency based on
  criticality and cost. Use when asked to "assess/pentest/security-review the
  <system>", "how exposed is <X>", "how often should we test <Y>", or to work
  through the surfaces in attacksurface.md one by one. Produces a concrete,
  prioritized findings list and a cadence, and feeds results back into the
  inventory.
---

# Assess an attack surface

Take one system (or a named few) from `docs/security/attacksurface.md` and assess
its real exposure efficiently — depth proportional to criticality, no wasted
motion — then set how often it should be re-tested.

## Authorization first (hard gate)

Only assess systems the user **owns or is clearly authorized to test**. Static
review of our own repo/config is always fine. **Active probing** (network scans,
auth fuzzing, live exploit attempts, hitting third-party vendor APIs beyond
normal use) requires the target be ours and the user's explicit go-ahead for
that run. Never attack a third party's infrastructure; for vendors (Clerk,
Supabase, Vercel, GitHub, LLM providers) assess **our configuration of them**,
not the vendor's own systems. When in doubt, ask one crisp question.

## Method (scale depth to criticality)

1. **Frame the target.** Pull its entry from the inventory: type, exposure, auth,
   defenses, criticality, and the listed "common misconfigs". That list is your
   starting test plan.
2. **Enumerate entry points.** For each audience in Exposure, what can that
   audience reach? PUBLIC routes/ports, TOKEN-gated APIs, KEY-guarded secrets,
   OUTBOUND calls that carry data out. Draw the trust boundary explicitly.
3. **Test against a standard checklist + the platform-specific misconfigs:**
   - **Web/API:** authn (token verification, issuer/audience, expiry), authz
     (IDOR / cross-tenant / missing `user_id` filter), input validation & SSRF,
     CORS, rate limiting, secret/PII leakage in responses/logs, security headers,
     unauth debug/metrics/health endpoints.
   - **DB:** who can reach it and from where (public vs private), credential
     handling, RLS vs app-only authz, backups/retention, injection.
   - **Infra/host:** exposed ports & security-group scope, SSH exposure, patch
     level, container isolation, metadata-service (IMDSv2), secret-at-rest.
   - **Identity/secret:** blast radius, rotation, least-privilege of the
     principal, test-vs-live key separation, storage location.
   - **Pipeline:** secret exposure to untrusted PRs, action pinning (SHA vs tag),
     branch protection, `GITHUB_TOKEN` scope, deploy path integrity.
   - **Outbound/vendor:** what data leaves, key scope & leak paths, egress
     controls, response-driven injection.
4. **Verify, don't assume.** Confirm each finding in the code/config (or, when
   authorized and safe, by observing behavior). Prefer the cheapest evidence that
   settles it. Distinguish **confirmed** from **plausible/needs-verification**.
5. **Report** findings ranked by severity (exploitability × blast radius), each
   with: what, where (`file:line` or resource), why it matters, and the fix.

## Recommend a testing frequency (criticality × cost)

Set a cadence per surface. Higher criticality → more often; higher assessment
cost → less often, and lean on cheap continuous checks between deep passes.

Baseline by criticality (deep manual/assisted assessment):

| Criticality | Baseline cadence |
|-------------|------------------|
| C1 catastrophic (crown jewels, prod host, auth, all-account keys) | monthly + on any change to it |
| C2 high | quarterly + on change |
| C3 moderate | semi-annually + on change |
| C4 minor | annually / opportunistically |

Then adjust:

- **Change-driven beats calendar:** always reassess a surface when its code,
  config, exposure, or dependencies change (wire this to CI/PRs where possible).
- **Cost lever:** if a full pass is expensive, split it — run the cheap
  **continuous** controls often (secret scanning, dependency/CVE alerts, IaC/
  config linting, security-header and TLS checks, `docs/security/prompt-injection.md`
  eval suite for the agent) and reserve the **expensive** manual review for the
  baseline cadence.
- **Exposure lever:** anything PUBLIC or KEY-guarded with C1/C2 blast radius gets
  the shorter interval; INTERNAL/OUTBOUND-only can relax one step.
- State the recommendation as: cadence + trigger events + which cheap checks run
  continuously in between. Give the reasoning in one line (criticality, exposure,
  cost).

## Close the loop

- Write findings somewhere durable (a dated section in `docs/security/`, or
  inline TODOs), and update the target's entry in `docs/security/attacksurface.md`
  — refresh Defenses, move resolved items out of "misconfigs to test", and record
  the chosen cadence + last-assessed date.
- If assessment revealed a new system or secret, hand back to the
  `attack-surface` skill to add it.

## Guardrails

- Read/analyze/report = autonomous. **Active probing, sending traffic to a
  target, or anything that spends money or could disrupt a live system = confirm
  first** (one question, recommended default), per the risk×leverage trust
  boundary.
- Never exfiltrate or display real secret values; reference by name/location.
- Free-tier only for any live LLM calls used in assessment (project policy).
