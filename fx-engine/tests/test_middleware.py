"""Middleware tests."""

import uuid

from starlette.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_includes_trace_id_header() -> None:
    """GET /healthz response includes an X-Trace-ID header."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert "X-Trace-ID" in response.headers


def test_trace_id_is_valid_uuid4() -> None:
    """Generated X-Trace-ID values are valid UUID4 strings."""
    response = client.get("/healthz")
    trace_id = response.headers["X-Trace-ID"]
    parsed = uuid.UUID(trace_id, version=4)
    assert str(parsed) == trace_id


def test_client_supplied_trace_id_is_honoured() -> None:
    """Client-provided X-Trace-ID is echoed in the response."""
    supplied_trace_id = "client-trace-abc123"
    response = client.get("/healthz", headers={"X-Trace-ID": supplied_trace_id})
    assert response.status_code == 200
    assert response.headers["X-Trace-ID"] == supplied_trace_id
