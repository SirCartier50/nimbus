"""Observability (PROD-6), right-sized for a single-box deployment:

  - structured JSON logs (LOG_FORMAT=json; plain text stays the dev default)
  - a request id on every request: honored from X-Request-ID if the proxy set
    one, generated otherwise, echoed back in the response header, and stamped
    onto every log line emitted while handling that request (contextvar-based,
    so it survives awaits and thread hops started from the request context)
  - Prometheus /metrics: request counts + latency histograms, labeled by ROUTE
    TEMPLATE (/api/files/{session_id}, not the concrete URL — unbounded label
    cardinality is how a metrics endpoint OOMs its scraper)
  - Sentry error tracking, enabled only when SENTRY_DSN is set

Self-hosted Grafana/Prometheus/Loki was considered and rejected for now: it's
more infrastructure to babysit than the product itself. Logs go to stdout for
`docker logs`/CloudWatch, errors go to Sentry's free tier, and /metrics is
there for whenever a scraper shows up.
"""
import json
import logging
import os
import time
import uuid
from contextvars import ContextVar

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

HTTP_REQUESTS = Counter(
    "nimbus_http_requests_total",
    "HTTP requests processed",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "nimbus_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    # Chat turns run minutes; the default buckets top out at 10s.
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600, 1800),
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            entry["request_id"] = rid
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging() -> None:
    """Configure the root logger once per process. JSON when LOG_FORMAT=json
    (what the containers set), readable text otherwise (bare dev runs)."""
    handler = logging.StreamHandler()
    if os.getenv("LOG_FORMAT", "text").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


def setup_sentry() -> None:
    """Error tracking, strictly opt-in via SENTRY_DSN. Tracing stays off — this
    is for exceptions, not APM billing surprises."""
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(dsn=dsn, traces_sample_rate=0.0, environment=os.getenv("SENTRY_ENVIRONMENT", "production"))
    logging.getLogger("observability").info("Sentry error tracking enabled")


def _route_template(request: Request) -> str:
    # Only available after routing ran (i.e. post-call_next); concrete paths
    # like /api/files/<uuid> collapse to their template.
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    return "unmatched"


async def observability_middleware(request: Request, call_next):
    """Outermost middleware: request id + metrics see every request, including
    ones auth later rejects."""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    token = request_id_var.set(rid)
    start = time.perf_counter()
    status = "500"  # if call_next raises, the request still gets counted
    try:
        response = await call_next(request)
        status = str(response.status_code)
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        route = _route_template(request)
        if route != "/metrics":  # scraping itself is noise
            HTTP_REQUESTS.labels(request.method, route, status).inc()
            HTTP_LATENCY.labels(request.method, route).observe(time.perf_counter() - start)
        request_id_var.reset(token)


def metrics_endpoint() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
