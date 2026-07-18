// SSE soak: hold several concurrent /api/chat/stream turns and verify every
// stream delivers a terminal event (final or error) — no hung streams, no
// dropped finalization. k6 buffers the whole response body, which is fine here:
// the assertion is about stream COMPLETION, not incremental delivery.
import http from "k6/http";
import { check } from "k6";
import { SharedArray } from "k6/data";

const BASE = __ENV.BASE_URL || "http://backend:8000";

const tokens = new SharedArray("tokens", () =>
  open("/tokens/tokens.txt").trim().split("\n")
);

export const options = {
  vus: 6,
  duration: "60s",
  thresholds: { checks: ["rate>0.99"] },
};

export default function () {
  const token = tokens[(__VU - 1) % tokens.length];
  const res = http.post(
    `${BASE}/api/chat/stream`,
    JSON.stringify({ message: "Explain EC2 briefly." }),
    {
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      timeout: "120s",
    }
  );
  check(res, {
    "stream 200": (r) => r.status === 200,
    "stream reached a terminal event": (r) =>
      r.body && (r.body.includes('"final"') || r.body.includes('"error"')),
    "stream not buffered by proxy header": (r) => r.headers["X-Accel-Buffering"] === "no",
  });
}
