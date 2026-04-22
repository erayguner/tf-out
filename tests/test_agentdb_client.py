"""Tests against a tiny in-process stub sidecar (no Node needed)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.memory.agentdb_client import AgentDBClient


class _StubHandler(BaseHTTPRequestHandler):
    routes: dict[str, Callable] = {}

    def log_message(self, *a, **kw):  # keep pytest output clean
        pass

    def _write(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle(self):
        if self.headers.get("authorization") != "Bearer test-token":
            return self._write(401, {"error": "unauthorised"})
        handler = self.routes.get(f"{self.command} {self.path}")
        if not handler:
            return self._write(404, {"error": "not found"})
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        try:
            self._write(200, handler(body))
        except Exception as exc:
            self._write(500, {"error": str(exc)})

    do_GET = do_POST = _handle


@pytest.fixture
def sidecar():
    srv = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{srv.server_port}"
    yield url
    srv.shutdown()


# ---- tests ---------------------------------------------------------------


def test_health_ok(sidecar):
    _StubHandler.routes = {"GET /healthz": lambda _b: {"ok": True}}
    client = AgentDBClient(sidecar, token="test-token", timeout_seconds=2)
    r = client.health()
    assert r.ok
    assert r.data == {"ok": True}


def test_unauth_returns_error(sidecar):
    _StubHandler.routes = {"GET /healthz": lambda _b: {"ok": True}}
    client = AgentDBClient(sidecar, token="wrong", timeout_seconds=2)
    r = client.health()
    assert not r.ok
    assert "401" in r.error


def test_store_sends_expected_payload(sidecar):
    captured = {}

    def _store(body):
        captured.update(body)
        return {"stored": True}

    _StubHandler.routes = {"POST /store": _store}

    client = AgentDBClient(sidecar, token="test-token")
    r = client.store(
        namespace="proj-x",
        text="run summary",
        metadata={"outcome": "success"},
        outcome="success",
        correlation_id="cid-1",
    )
    assert r.ok
    assert captured["namespace"] == "proj-x"
    assert captured["correlation_id"] == "cid-1"


def test_filter_blocks_secret_before_send(sidecar):
    calls = {"count": 0}

    def _store(_body):
        calls["count"] += 1
        return {"stored": True}

    _StubHandler.routes = {"POST /store": _store}

    client = AgentDBClient(sidecar, token="test-token")
    # GitHub PAT in the text — must be blocked client-side
    r = client.store(
        namespace="x",
        text="leaked ghp_" + "a" * 40,
        metadata={},
        outcome="success",
        correlation_id="cid-2",
    )
    assert not r.ok
    assert "github_pat" in r.error
    assert calls["count"] == 0  # never hit the wire


def test_circuit_breaker_opens_after_failures(sidecar):
    # 500 on every call
    _StubHandler.routes = {"POST /store": lambda _b: (_ for _ in ()).throw(RuntimeError("boom"))}
    client = AgentDBClient(sidecar, token="test-token", timeout_seconds=1)
    for _ in range(3):
        r = client.store(namespace="x", text="ok", metadata={}, outcome="success", correlation_id="c")
        assert not r.ok
    # Fourth call: circuit open, no network
    r = client.store(namespace="x", text="ok", metadata={}, outcome="success", correlation_id="c")
    assert r.error == "circuit open"


def test_unreachable_sidecar_is_fail_open():
    client = AgentDBClient("http://127.0.0.1:1", token="t", timeout_seconds=0.5)
    r = client.health()
    assert not r.ok
    # Error is non-raising
    assert r.error
