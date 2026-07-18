// Smoke: liveness + readiness must hold under trivial load before anything else.
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE_URL || "http://backend:8000";

export const options = {
  vus: 2,
  duration: "10s",
  thresholds: {
    http_req_failed: ["rate==0"],
    http_req_duration: ["p(95)<200"],
  },
};

export default function () {
  check(http.get(`${BASE}/health`), { "liveness 200": (r) => r.status === 200 });
  check(http.get(`${BASE}/health/ready`), { "readiness 200": (r) => r.status === 200 });
}
