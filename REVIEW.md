# Nimbus — Senior Engineering Review + Professional Design Critique (2026-07-09)

> Follow-up to the inline CEO + Engineering reviews in HANDOFF.md. This pass re-reads
> those, reviews the codebase as it stands today (including the uncommitted UI redesign
> in the working tree), and adds a harsh professional-designer critique of the UI.
> Items marked **[FIXED this session]** were executed immediately after this review.

---

## Part 1 — Senior Lead Engineer Review

### Where the earlier reviews stand

The 2026-06 CEO review said: trust is the core risk, Bodyguard is the differentiator,
Requirements Agent is the biggest missing UX piece. The Eng review said: kill
process-global state, per-user credentials, config-driven executor. **Almost all of
that landed**: STS AssumeRole replaced stored keys, Bodyguard is per-user, the
pipeline is a real LangGraph with Requirements → Architect → Tier-1 loop → critic →
gate → executor → validator → summary, cost is real (Pricing API + static fallback),
and the suite is 222 tests against a real Postgres. The backend is in genuinely good
shape for a pre-launch product. What follows is what's still wrong, ranked.

### ENG-1 (HIGH) — The flagship feature is faked in the UI. **[FIXED this session]**
`POST /api/chat/stream` (SSE, per-node LangGraph progress) is built and tested —
and **no frontend code calls it**. The chat page POSTs plain `/chat` and fabricates
an "activity trace" client-side from hardcoded strings ("Analyzing request with
Groq…", "Infrastructure plan generated") written before/after the response arrives.
In a product whose brand promise is *transparency about what agents are doing*,
showing a fabricated log is worse than showing nothing: it's a simulated audit
trail. The CEO review called agent visibility the differentiator; today it's
theater. Fix: drive the composer through `/chat/stream`, render real progress
events live, fall back to `/chat` if the stream fails.

### ENG-2 (HIGH) — SSE turn is lost if the client disconnects. **[FIXED this session]**
In `chat_stream`, the graph runs inside the response generator
(`loop.run_in_executor(None, produce)`), and `_finalize_turn` runs after the stream
loop. If the browser disconnects mid-deploy (tab close, refresh), Starlette cancels
the generator: **real AWS resources may have been created, but no Deployment row,
no history, no ui_messages are ever written.** The plain `/chat` endpoint doesn't
have this bug (FastAPI completes the handler regardless of client state). Since
ENG-1 makes streaming the primary path, this must be fixed first: run the turn +
finalize in a background task that owns its own DB session (`async_session_local`),
and let the SSE generator merely *observe* it via a queue. Disconnect then kills
the observer, never the turn.

### ENG-3 (HIGH) — Still no rate limiting (SEC-2). **[FIXED this session]**
Every `/api/chat` call fans out to LLM + boto3 + Postgres. One authenticated user
in a `while true; curl` loop spends real money (Bedrock tokens, AWS API calls) and
can starve the single-process backend. All routes are Clerk-authed, so a per-user
in-process token bucket in middleware is cheap and correct at current scale; move
the counters to Redis when PROD-3 lands. Chat should get a tight budget (LLM cost),
reads a loose one.

### ENG-4 (MED) — "Unlink repository" doesn't unlink. **[FIXED this session]**
`settings/page.tsx`'s Unlink button only resets React state; there is no
`DELETE /api/settings/github`. Reload and the repo is still linked. Same class of
bug for AWS "Update role" (cosmetic only — it just reopens the form — but there is
no way to actually disconnect AWS either). Add a delete endpoint and wire it.

### ENG-5 (MED) — Dashboard "Estimated monthly cost" is a fabricated number. **[FIXED this session]**
`UsageWidget` shows `runningEc2 * $3.65` (the public-IPv4 line item only) as
"Estimated monthly cost". The backend has a real per-resource cost endpoint; the
pipeline has a real pricing engine. Showing a made-up figure on the *money* surface
is the exact anti-pattern PIPELINE_PLAN §6 was written to kill. Until an aggregate
endpoint exists, label honestly (per-resource breakdown on click) instead of
inventing a total.

### ENG-6 (MED) — Error turns are never persisted.
When `run_turn` raises, the route 500s; the user's message and the error reply
exist only in client state. Reload the session and they're gone — and the LLM
`history` in Postgres has diverged from what the user saw. Low-frequency but
confusing. Consider persisting a `{"role":"assistant","error":true}` ui_message on
the 500 path. (Deferred — needs a small design decision about retry semantics.)

### ENG-7 (LOW, batch) — Small correctness/consistency items.
- `utils/llm/__init__.py:63` — unknown-provider error says "Options: bedrock,
  groq, openrouter" but huggingface is supported. **[FIXED]**
- `plan_is_destructive` uses substring matching (`"stop" in action`) — fine while
  actions come from the fixed registry, but a `create_stopped_*`-style action would
  false-positive. Tighten to prefix/verb matching when the registry grows.
- `routes/sessions.py` imports `_get_owned_session` from `routes/chat` — private
  cross-route import; move to a shared helper module on the next touch.
- `_load_session` commits a new Session row *before* the turn runs — a pipeline
  crash leaves an empty titled conversation in the sidebar.
- `AWSGate`'s `nimbus_aws_connected` localStorage cache isn't keyed by user — on a
  shared browser, user B briefly sees user A's connected state (flash only; the
  background check corrects it).

### ENG-8 (Architecture) — The real blocker for PROD-4 (Kubernetes) is process-local state.
Three things silently assume exactly one backend process: Bodyguard's daemon +
in-memory `state`, the assume-role credential cache, and the rate limiter above.
Running 2 replicas today means two Bodyguards patrolling (duplicate stop actions)
and split rate buckets. **Do not write K8s manifests before**: (a) Bodyguard is
extracted to its own single-replica worker (or leader-elected), and (b) shared
state moves to Redis (PROD-3). This ordering — Redis → Bodyguard extraction → K8s
— should be explicit in the task list; it now is.

### Testing posture
Backend: strong (222 passing against a disposable Postgres; mocked AWS/LLM
everywhere). Frontend: **zero tests** — TEST-7 is honestly open; the highest-value
first tests are the chat-page reducer logic (message/plan/confirm flow), not
component snapshots. Live-model testing policy: per the user's rule, any live LLM
verification uses **free providers only** (Groq/OpenRouter/HF); Bedrock frontier
models are never exercised by tests.

---

## Part 2 — Professional Web Designer Critique (harsh, as requested)

**Verdict: competent template, not a designed product.** The current UI is the
default "dark AI SaaS" recipe — near-black background, glass cards, one blue
accent, gradient-span headlines, glow shadows. Nothing is broken, everything is
anonymous. A hiring-bar designer would spot ~15 tells in the first minute:

### The tells

1. **The formula headline, three times.** "Three Agents. *One Mission.*" /
   "Cloud Made *Simple*" — the two-word-period-gradient-span pattern is the single
   most recognizable AI-generated-landing-page trope of the last two years. One
   gradient span per page, maximum, and never in a formula. **[FIXED — section
   headers are now plain ("Meet the agents", "How it works"); the hero keeps the
   page's single gradient moment]**
2. **Infinite shimmer on the hero phrase.** `text-shimmer` loops forever on the
   most important words on the site. Casino signage. Motion should happen once, on
   entrance, then stop — permanent animation on body-level content reads cheap and
   hurts reading. **[FIXED — now a static two-tone gradient]**
3. **The starburst background.** 18 blurred wisps radiating from the section
   center ("hyperdrive") sits *behind the hero copy and the chat preview*,
   producing noise exactly where contrast matters most. Ambient background art
   should support the focal point, not compete with it, and its vanishing point is
   anchored to a grid section, so it drifts as content reflows. **[FIXED —
   brightness halved and the hot white core reduced to a soft glow; verified by
   before/after screenshots]**
4. **Three icon systems at war.** Phosphor icons (agents), hand-rolled stroke SVGs
   (chat/dashboard, with inconsistent stroke widths 1.5/2), and **raw emoji**
   (🖥🪣🗄🐘 on Services). Emoji as product iconography is the fastest way to look
   amateur — they render differently on every OS and carry no brand.
   **[FIXED — Services now uses the same Phosphor family]**
5. **Fake stats.** "AWS Services 5+", "Deploy Time ~30s", "Cost Awareness Built
   In" — the last one isn't a statistic, and the first contradicts the Services
   page (15 resource types). Invented-precision stat bars are a template tell;
   real numbers or none. **[FIXED — real, consistent claims]**
6. **Brand-name soup.** "Powered by Amazon Nova AI" (hero badge), "Powered by
   Amazon Nova" (agent card), "Powered by Amazon Bedrock" (footer) — and the
   product now supports four providers, so all three claims are stale. Say it
   once, accurately. **[FIXED]**
7. **No focus states anywhere.** The project's own guardrails demand
   hover/focus-visible/active on every interactive element; nothing on the site
   has a visible keyboard focus ring. That's not polish, that's an accessibility
   failure. **[FIXED — global focus-visible ring]**
8. **The most important button in the product is 12px.** The Deploy confirm —
   the moment real money starts — is a `text-xs` button inside a chat bubble,
   visually junior to the marketing site's "Start Building". Approval gates should
   be the most deliberate-feeling control on the screen. **[FIXED — larger,
   deliberate confirm row]**
9. **A fabricated activity log** (see ENG-1). Design-wise this is the worst
   offense on the product: the one surface meant to build trust is staged.
   **[FIXED — real stream]**
10. **Desktop-only.** No mobile nav (links just crush), fixed `w-64` sidebar, no
    breakpoint handling anywhere in the app shell. In 2026 this reads as a student
    project. **[PARTIALLY FIXED — mobile nav + collapsing sidebar; full mobile
    audit still open]**
11. **Monotone surface recipe.** Every card on every page is `glass rounded-xl
    p-6` + `text-xs text-slate-500` label. There's no surface hierarchy (base /
    elevated / floating), so pages feel flat despite the blur. The type scale is
    timid too — section headings at 30–36px with body at 14px gives almost no
    hierarchy between "hero" and "card label".
12. **Dead page.** `/terminal` is reachable only by typing the URL (it's not in
    the navbar), fakes terminal boot lines ("Nimbus Terminal v1.0 — Connecting…"),
    and duplicates the dashboard's Bodyguard panel. Either it earns its place in
    the nav or it goes. (Left for a product decision — recommend folding into
    Dashboard.)
13. **Welcome message is a wall of bold text.** Suggested prompts belong in
    clickable chips under the composer, not as shouted markdown in the first
    bubble. **[FIXED — suggestion chips]**
14. **Assistant output renders raw.** Only `**bold**` is parsed; any list, code
    fence, or heading from the model prints as literal markdown characters.
15. **Meaningless bar chart.** The dashboard usage bars normalize each service
    against the *largest count* — four bars whose lengths mean nothing relative to
    any capacity or budget. Data-viz that decorates instead of informs.

### What's actually good (keep it)

The ChatPreview hero visual (real product UI as the hero image) is a genuinely
strong move. The asymmetric featured-agent grid, the Outfit/Geist pairing, the
single ion accent family, the restrained grain overlay, the session sidebar
interaction pattern, and the STS onboarding flow in Settings are all solid. The
bones are fine — the problem is template-default styling decisions layered on top.

### Direction (one sentence)

Stop decorating a dark template and start art-directing the one thing competitors
can't copy: **the live agent pipeline** — make the real stream the visual
centerpiece of the chat, keep marketing claims literal, unify to one icon family,
one gradient moment, one bold CTA per screen.
