// Baseline + capacity: the questions this answers, in one run —
//   1. Under-capacity chat turns (arrival below MAX_CONCURRENT_TURNS×1/duration):
//      zero 503s, and p95 turn latency ≈ mock latency + pipeline overhead.
//   2. A saturation burst: turns beyond capacity get an IMMEDIATE 503 (admission
//      control), never a slow queue.
//   3. DB reads stay fast THROUGHOUT — the dedicated turn executor must isolate
//      long turns from the rest of the API (the PROD-1 guarantee under test).
//
// Each VU authenticates as its own minted user (own rate bucket, own DB rows).
import http from "k6/http";
import { check, sleep } from "k6";
import { SharedArray } from "k6/data";
import { Rate, Trend } from "k6/metrics";
import exec from "k6/execution";

const BASE = __ENV.BASE_URL || "http://backend:8000";

// 503 is designed admission-control behavior under saturation, not a failure.
http.setResponseCallback(http.expectedStatuses(200, 503));

const tokens = new SharedArray("tokens", () =>
  open("/tokens/tokens.txt").trim().split("\n")
);

const turn503 = new Rate("turn_rejected_503");
const turnOk = new Rate("turn_ok");
const readDuration = new Trend("read_duration", true);

export const options = {
  scenarios: {
    // Steady DB reads for the whole run — must stay fast even during the burst.
    reads: {
      executor: "constant-arrival-rate",
      rate: 20, timeUnit: "1s", duration: "2m",
      preAllocatedVUs: 10, maxVUs: 30,
      exec: "reads",
    },
    // Under-capacity turns: 4 concurrent against MAX_CONCURRENT_TURNS=8.
    turns_nominal: {
      executor: "constant-vus",
      vus: 4, duration: "60s",
      exec: "turn",
    },
    // Saturation burst: 30 concurrent against 8 slots → expect 503s, all fast.
    turns_burst: {
      executor: "constant-vus",
      vus: 30, duration: "30s", startTime: "75s",
      exec: "turn",
    },
  },
  thresholds: {
    read_duration: ["p(95)<250"],                          // reads unharmed by turn load
    "turn_rejected_503{scenario:turns_nominal}": ["rate==0"], // under capacity → never rejected
    checks: ["rate==1"],                                   // every response well-formed
    http_req_failed: ["rate<0.01"],                        // real failures only (503 expected above)
  },
};

function authHeaders() {
  const token = tokens[(__VU - 1) % tokens.length];
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

export function reads() {
  const res = http.get(`${BASE}/api/sessions?limit=5`, { headers: authHeaders() });
  readDuration.add(res.timings.duration);
  check(res, { "sessions 200": (r) => r.status === 200 });
}

export function turn() {
  const res = http.post(
    `${BASE}/api/chat`,
    JSON.stringify({ message: "What is Amazon S3?" }),
    { headers: authHeaders(), timeout: "120s" }
  );
  const scenario = { scenario: exec.scenario.name };
  turn503.add(res.status === 503, scenario);
  turnOk.add(res.status === 200, scenario);
  check(res, {
    "turn 200 or clean 503": (r) => r.status === 200 || r.status === 503,
    "503 carries Retry-After": (r) => r.status !== 503 || r.headers["Retry-After"] !== undefined,
  });
  if (res.status === 503) sleep(1); // clients back off on rejection; don't hot-loop
}
