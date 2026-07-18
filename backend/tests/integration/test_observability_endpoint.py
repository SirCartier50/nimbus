"""Request ids + /metrics through the real app/middleware chain."""
import pytest

from tests.conftest import requires_db

pytestmark = [requires_db, pytest.mark.asyncio]


async def test_every_response_carries_a_request_id(client):
    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID")


async def test_incoming_request_id_is_honored_not_replaced(client):
    resp = await client.get("/api/sessions", headers={"X-Request-ID": "proxy-set-this"})
    assert resp.headers["X-Request-ID"] == "proxy-set-this"


async def test_metrics_endpoint_exposes_route_templates_not_raw_paths(client):
    # Drive a request through a parameterized route first…
    await client.get("/api/files/not-a-real-session-id")
    resp = await client.get("/metrics")

    assert resp.status_code == 200
    body = resp.text
    assert "nimbus_http_requests_total" in body
    # …and confirm the label is the template, not the concrete path segment
    # (concrete ids would blow up metric cardinality). FastAPI reports the
    # route's own path without the router prefix — bounded either way.
    assert "/files/{session_id}" in body
    assert "not-a-real-session-id" not in body
