# Load tests (PROD-7)

k6 scenarios against an **isolated stack** — its own throwaway Postgres (tmpfs), a
mock OpenAI-compatible LLM, and a local JWKS issuer so tests can mint unlimited
valid JWTs. Nothing here touches Supabase, Clerk, AWS, or a paid model provider.

## How auth works without Clerk

The backend verifies JWTs against `{CLERK_ISSUER}/.well-known/jwks.json`.
`gen_tokens.py` generates an RSA keypair, writes a JWKS document, and signs N
tokens (`sub=loadtest-user-i`, 24h expiry). The stack serves that JWKS from a
static server and sets `CLERK_ISSUER` to it — so the real verification code path
runs (RS256, issuer check, JWKS fetch), and every k6 VU is a distinct user with
its own rate bucket and DB rows.

## How turns run without a real LLM

`mock_llm.py` serves `/v1/chat/completions` with a canned reply after
`MOCK_LATENCY_MS` (default 300). The backend points at it via
`OPENROUTER_BASE_URL`, so a k6 chat turn exercises the FULL pipeline — auth,
rate limiter, LangGraph graph, Postgres persistence, SSE — with model latency as
a controlled variable. Raise `MOCK_LATENCY_MS` to simulate slow models and reach
saturation with fewer VUs.

## Run it

```bash
cd loadtest
# 1. Mint identities (once; rewrites ./out)
docker run --rm -v "$PWD:/lt" -w /lt -e N_USERS=50 python:3.11-slim \
  sh -c "pip install -q 'PyJWT[crypto]' && python gen_tokens.py"
# 2. Stack up (backend on host :8001, beside the dev stack on :8000)
docker compose -f docker-compose.loadtest.yml up -d --build
# 3. Schema (throwaway DB, so create_all is fine — no alembic ceremony)
docker compose -f docker-compose.loadtest.yml exec backend python -c "
import asyncio
import db.models
from db.engine import engine, Base
async def m():
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
asyncio.run(m())
"
# 4. Tests (k6 in docker, on the stack's network)
docker run --rm --network nimbus-loadtest_default \
  -v "$PWD/k6:/scripts:ro" -v "$PWD/out:/tokens:ro" \
  grafana/k6 run /scripts/smoke.js        # then baseline.js, stream_soak.js
# 5. Tear down
docker compose -f docker-compose.loadtest.yml down
```

(On Git Bash, prefix container paths with `//` — e.g. `//scripts/smoke.js`.)

## Scenarios

- **smoke.js** — liveness/readiness sanity gate (p95 < 200ms, zero failures).
- **baseline.js** — the capacity story in one 2-minute run: steady DB reads
  throughout; 4 concurrent turns for 60s (under `MAX_CONCURRENT_TURNS=8`);
  then a 30-VU saturation burst. Thresholds encode the PROD-1 guarantees:
  nominal turns are NEVER 503'd, saturated turns get an instant 503 with
  Retry-After (admission control, not queueing), and reads stay fast while
  every turn slot is busy (executor isolation).
- **stream_soak.js** — 6 concurrent SSE turns for 60s; every stream must reach
  a terminal event (`final`/`error`) and carry `X-Accel-Buffering: no`.

## Baseline — 2026-07-15 (dev machine, Docker Desktop/Windows, 1 uvicorn worker, MAX_CONCURRENT_TURNS=8, mock latency 300ms)

All thresholds green. Numbers are a *relative* baseline for regression
comparison, not production capacity (that gets re-measured on the EC2 target):

| Metric | Result |
|---|---|
| Health checks | ~586 req/s at p95 3.9ms (2 VUs — not a ceiling) |
| DB reads (sessions list) during full turn saturation | p95 **7.2ms** |
| Full pipeline turn (300ms model) | p95 **324ms** → ~24ms pipeline overhead |
| SSE stream turn | p95 335ms, 1,124/1,124 streams reached terminal event |
| Nominal turns (4 concurrent / 8 slots) | **0** rejected of 759 |
| Burst (30 concurrent / 8 slots) | 660 instant 503s (all with Retry-After), 0 malformed responses, reads unaffected |
| Successful full turns in the 2-min run | 1,503 |

Interpretation: one instance sustains `MAX_CONCURRENT_TURNS` concurrent
deployments and read traffic degrades by ~nothing when saturated; overload is
shed instantly instead of queueing. Scale turns by raising
`MAX_CONCURRENT_TURNS` (thread cost only) or adding replicas once PROD-3
(Redis) lands.
