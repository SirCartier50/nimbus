# Model-drop checklist

Run this when a new/better model becomes available, or before changing the model
Nimbus uses in production. The point is to make capability a **measured** decision
instead of a guess — and specifically to know when the model is good enough that
hand-built scaffolding can be safely removed (the Bitter-Lesson thesis: as the
general method improves, hand-coded knowledge becomes dead weight).

## Run it

```bash
cd backend
python -m evals.run --provider openrouter --repeat 3 --out evals/out/<model>.json
```

- Use a **free** provider only (Groq / OpenRouter / HF) — project policy; never
  a paid/frontier endpoint for testing.
- Pin the exact model with the provider's `*_MODEL` env var (e.g.
  `OPENROUTER_MODEL=...`) so the report records what you actually tested.
- `--repeat 3` runs each task 3× and only passes a task if **every** run passed.
  A model that plans correctly only sometimes is not one to lean on.

## Read the results

- **Overall N/5** — baseline planning competence. A model below ~4/5 here is not
  ready to be the product's default at all.
- **Generic-path capability (the #4 signal)** — the `sqs_queue` probe has *no*
  curated tool, so a correct plan *must* drive the generic `AWS::…` Cloud Control
  path. This is the load-bearing number for the decision below.

## The decision this gates: `ARCHITECT_RESOURCE_PREFERENCE`

Set in the environment; read by the Architect (`agents/architect.py`). Values:

| value | meaning | when |
|-------|---------|------|
| `curated` (default) | Prefer the 15 curated tools; generic only for the long tail | today's models |
| `balanced` | No preference; pick per request | transitional |
| `generic` | Prefer `AWS::…` types; curated only for special handling | once evidence supports it |

**Flip toward `generic` only when**, across **two or more** capable models,
`--pref generic` shows: generic-probe tasks pass **and** the curated tasks
(`s3_uploads`, `vpc_subnets`, `lambda_http`, `free_tier_guard`) still pass — i.e.
the model drives the generic path without losing correctness or free-tier safety.

```bash
python -m evals.run --provider openrouter --pref generic --repeat 3
```

Even at `generic`, keep the curated tools for what Cloud Control genuinely can't
do: precise cost estimates, free-tier enforcement, and the special actions
(stop/start EC2, empty-then-delete S3, Lambda execution-role bootstrap). The goal
is to stop *growing* the registry and let the model cover AWS's breadth — not to
delete the parts that carry real non-model value.

## What to do with a regression

If a new model **fails** tasks an older one passed, that's the harness doing its
job — do not ship it as the default. File the failing task ids and the JSON
report, and keep the current default until a model clears the bar.
