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

- Tokens and base styles live in `frontend/app/globals.css`: the `ion-*` accent
  scale (`--color-ion-50`…`950`, built off `#2e9ee0`), dark base
  (`--background: #05070a`), Geist sans/mono + Outfit display font. Use these,
  not default Tailwind colors (indigo-500/blue-600 etc. were deliberately
  removed from this project).
- Established surface/effect classes: `.glass` / `.glass-light` (card
  treatment), `.bg-grain` (SVG noise overlay), `.glow-blue` /
  `.glow-blue-hover` (tinted shadow, not a blurred neon glow). Extend these
  rather than hand-rolling new card/shadow recipes.
- Tailwind v4 — config is CSS-based in `globals.css` (`@theme inline`), there is
  no `tailwind.config.js`.
- Already-installed UI deps: `@phosphor-icons/react` for icons, `framer-motion`
  for animation, `@clerk/nextjs` for auth. Use these before reaching for a new
  library.
- Animate `transform`/`opacity` only, spring-style easing, never
  `transition-all` — this is the project's own established rule (see
  `LoomBackground.tsx`). `prefers-reduced-motion` is already handled globally
  in `globals.css`; anything you animate must still degrade correctly under it.
- `:focus-visible` gets a visible ring globally already — every new
  interactive element needs hover/focus/active states, don't bypass the
  existing ring.
- Known debt, don't compound it: every card currently uses the identical flat
  `.glass` treatment with no base/elevated/floating layering, and heading vs.
  body type scale is timid in places (tracked as UX-4 in `DECISIONS.md`). Give
  new surfaces real depth instead of defaulting to another flat `.glass` div.

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
