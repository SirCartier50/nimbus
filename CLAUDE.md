# CLAUDE.md — Nimbus

Agentic AWS management app: FastAPI backend (`backend/`) + Next.js 16 App Router
frontend (`frontend/`, TypeScript, React 19). This is a real multi-route app with
an established component library and design system — treat frontend work as
editing/extending it, not generating a standalone HTML page.

See `DECISIONS.md` for the non-obvious decisions (and their *why*) and the work
that's genuinely still open — it's the live cross-machine continuity doc. For
"what shipped and how," read the code and `git log`, not a prose changelog. A
frozen historical narrative lives at `docs/archive/HANDOFF-2026-07-18.md`.

## Frontend design system (already built — reuse it, don't reinvent it)

**Source of truth: `frontend/app/globals.css` and the existing components.** Read
them and match what's there — the `ion-*` accent scale, the dark base, the
display/mono fonts, and the `.glass` / `.glass-light` / `.bg-grain` /
`.glow-blue` / `.glow-blue-hover` surface classes are all defined there with
their rationale in the comments. Don't transcribe or re-derive those values here;
extend the existing classes rather than hand-rolling new card/shadow recipes.

Non-obvious rules that reading the CSS won't tell you:

- Default Tailwind colors (indigo-500 / blue-600 etc.) were **deliberately
  removed** from this project — don't reintroduce them; stay on the `ion-*` scale.
- Tailwind v4, config is CSS-based in `globals.css` (`@theme inline`) — there is
  **no** `tailwind.config.js`.
- Use what's already installed before reaching for a new library — icons
  (`@phosphor-icons/react`), animation (`framer-motion`), auth
  (`@clerk/nextjs`). Check `package.json`.
- Animate `transform`/`opacity` only, spring-style easing, never
  `transition-all` (see `LoomBackground.tsx` for the pattern).
  `prefers-reduced-motion` is handled globally — anything you animate must still
  degrade correctly under it.
- A `:focus-visible` ring is applied globally — every new interactive element
  needs hover/focus/active states and must not bypass it.
- Known debt, don't compound it (UX-4 in `DECISIONS.md`): every card is the same
  flat `.glass` with no base/elevated/floating layering, and the type scale is
  timid. Give new surfaces real depth instead of another flat `.glass` div.

## Verifying frontend changes

- Dev server: `npm run dev` inside `frontend/`.
- Screenshot/QA: use the `gstack` skill's `browse` command (already set up for
  this project), or the Playwright e2e infra in `frontend/e2e/` (includes a
  real authenticated-session flow via `@clerk/testing`, cached in
  `playwright/.clerk/user.json`).
- Before calling frontend work done: `npx tsc --noEmit` and `npm run build`
  must both be clean. Docker note: `docker compose up` alone serves a stale
  image — use `docker compose build && docker compose up -d` to see new code
  in a container.

## Skill routing

Only skills that actually appear in the per-session available-skills list are
invokable via the Skill tool. Most of gstack's broader command family
(`/office-hours`, `/plan-*-review`, `/investigate`, `/qa`, `/review`, `/ship`,
`/spec`, etc.) are user-run slash commands, not Claude-invokable skills — don't
attempt to invoke them via the Skill tool just because they're documented
somewhere. `gstack` (its `browse` QA/screenshot workflow) is the one that
actually is.
