"""HTTP client for the AgentDB sidecar.

Designed to be **fail-open**: if the sidecar is down, slow, or errors, the
pipeline continues without memory. Losing memory degrades future learning,
but the user's Terraform output must never be held hostage by a sidecar
outage. All failures are audited.

Cross-cutting controls:

* Content filter (§11.2 / §11.6 memory-injection threat model) runs on every
  payload before it leaves the process. ``block``-severity findings abort
  the call.
* Circuit breaker trips after repeated failures; further calls short-circuit
  for ``break_duration_seconds`` without touching the network.
* Wall-clock timeout on every request.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..core.filters import FilterStack

log = logging.getLogger(__name__)


class SidecarUnavailable(RuntimeError):
    """Raised internally; callers should catch via SidecarResponse."""


@dataclass
class SidecarResponse:
    ok: bool
    data: dict = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0


class _CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, break_duration_seconds: float = 30.0):
        self._threshold = failure_threshold
        self._break = break_duration_seconds
        self._failures = 0
        self._open_until: float = 0.0

    def allow(self) -> bool:
        return time.monotonic() >= self._open_until

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = time.monotonic() + self._break
            log.warning("AgentDB sidecar circuit opened for %.0fs", self._break)


class AgentDBClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 5.0,
        filter_stack: FilterStack | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout_seconds
        self._filters = filter_stack or FilterStack()
        self._breaker = _CircuitBreaker()

    # ---- operations ---------------------------------------------------

    def health(self) -> SidecarResponse:
        return self._request("GET", "/healthz")

    def stats(self) -> SidecarResponse:
        return self._request("GET", "/stats")

    def store(
        self, *, namespace: str, text: str, metadata: dict[str, Any], outcome: str, correlation_id: str
    ) -> SidecarResponse:
        payload = {
            "namespace": namespace,
            "text": text,
            "metadata": metadata,
            "outcome": outcome,
            "correlation_id": correlation_id,
        }
        return self._filtered_post("/store", payload)

    def search(
        self, *, namespace: str, text: str, k: int = 5, min_confidence: float = 0.0, domain_filter: str | None = None
    ) -> SidecarResponse:
        payload = {
            "namespace": namespace,
            "text": text,
            "k": k,
            "min_confidence": min_confidence,
        }
        if domain_filter:
            payload["domain_filter"] = domain_filter
        return self._filtered_post("/search", payload)

    def prune(
        self, *, min_confidence: float = 0.3, min_usage: int = 0, max_age_seconds: int | None = None
    ) -> SidecarResponse:
        payload: dict[str, Any] = {"min_confidence": min_confidence, "min_usage": min_usage}
        if max_age_seconds:
            payload["max_age_seconds"] = max_age_seconds
        return self._request("POST", "/prune", payload)

    # ---- internals ----------------------------------------------------

    def _filtered_post(self, path: str, body: dict) -> SidecarResponse:
        # Memory-injection defence (§11.6): anything written to memory
        # passes through the same filter stack as user input. Secrets block.
        verdict = self._filters.scan(body)
        if verdict.blocked:
            return SidecarResponse(
                ok=False,
                error=f"blocked by filter: {[f.detector for f in verdict.findings if f.severity == 'block']}",
            )
        return self._request("POST", path, body)

    def _request(self, method: str, path: str, body: dict | None = None) -> SidecarResponse:
        if not self._breaker.allow():
            return SidecarResponse(ok=False, error="circuit open")

        url = self._base + path
        data = json.dumps(body or {}).encode() if body is not None else None
        req = urllib.request.Request(url=url, method=method, data=data)
        req.add_header("authorization", f"Bearer {self._token}")
        if data is not None:
            req.add_header("content-type", "application/json")

        started = time.monotonic()
        try:
            # Base URL is loopback HTTP; no TLS context needed.
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                out = json.loads(raw)
                self._breaker.record_success()
                return SidecarResponse(
                    ok=True,
                    data=out,
                    duration_ms=(time.monotonic() - started) * 1000,
                )
        except urllib.error.HTTPError as exc:
            self._breaker.record_failure()
            return SidecarResponse(
                ok=False,
                error=f"http {exc.code}: {exc.reason}",
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except Exception as exc:
            self._breaker.record_failure()
            return SidecarResponse(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=(time.monotonic() - started) * 1000,
            )
