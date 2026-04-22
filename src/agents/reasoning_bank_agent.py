"""ReasoningBank Agent — tail step that persists the run's trajectory.

Runs last so it can capture the final outcome. Fail-open — a sidecar
problem never fails the pipeline; it just leaves the trajectory unrecorded
and audits the failure.

The search side is exposed as ``similar_runs(query_text)`` so the
GovernanceAgent can pull prior-run context without depending on this
module being the one to actually invoke it.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..memory import AgentDBClient, ReasoningBank, Trajectory
from ..settings import Settings

log = logging.getLogger(__name__)


class ReasoningBankAgent:
    name = "reasoning_bank"

    def __init__(self, settings: Settings):
        self._s = settings
        self._bank = _make_bank(settings)

    # Pipeline tail step — stores the trajectory
    def run(self, ctx):
        if self._bank is None:
            ctx.audit.record(self.name, "skipped", "memory_disabled", "success", rationale="memory.enabled=false")
            return ctx

        outcome = _derive_outcome(ctx)
        trajectory = Trajectory(
            correlation_id=ctx.audit.run_id,
            scope=self._s.project.scope_id,
            environment=self._s.project.environment,
            outcome=outcome,
            resources_discovered=len(ctx.discovery.resources) if ctx.discovery else 0,
            counts=_bucket_counts(ctx),
            violations=[{"rule": v.rule, "severity": v.severity} for v in ctx.violations],
            validation_steps=ctx.validation.steps_passed if ctx.validation else [],
            rationale=_rationale(ctx, outcome),
        )
        response = self._bank.record(trajectory)
        ctx.audit.record(
            self.name,
            "trajectory_recorded" if response.ok else "trajectory_record_failed",
            trajectory.correlation_id,
            "success" if response.ok else "failure",
            rationale=response.error or f"namespace={self._bank.namespace}",
            duration_ms=response.duration_ms,
        )
        return ctx

    # Convenience: governance agent can call this directly
    def similar_runs(self, query_text: str, k: int = 5) -> list[dict[str, Any]]:
        if self._bank is None:
            return []
        return self._bank.search_similar(query_text, k=k)


# ---- helpers ---------------------------------------------------------------


def _make_bank(settings: Settings) -> ReasoningBank | None:
    mem = settings.memory
    if not mem.enabled:
        return None
    token = mem.sidecar_token or os.getenv("AI_TF_SIDECAR_TOKEN", "")
    if not token:
        log.warning("memory.enabled=true but no sidecar_token configured; disabling")
        return None
    client = AgentDBClient(
        base_url=mem.sidecar_url,
        token=token,
        timeout_seconds=mem.timeout_seconds,
    )
    namespace = mem.namespace or settings.project.scope_id or "default"
    return ReasoningBank(client=client, namespace=namespace)


def _derive_outcome(ctx) -> str:
    if ctx.validation and ctx.validation.fully_validated:
        return "success"
    if ctx.violations and any(v.severity == "deny" for v in ctx.violations):
        return "failure"
    return "partial"


def _bucket_counts(ctx) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in ctx.classified:
        counts[c.status] = counts.get(c.status, 0) + 1
    return counts


def _rationale(ctx, outcome: str) -> str:
    parts = [f"outcome={outcome}"]
    if ctx.discovery:
        parts.append(f"resources={len(ctx.discovery.resources)}")
    if ctx.violations:
        parts.append(f"violations={len(ctx.violations)}")
    if ctx.validation:
        parts.append(f"val_steps={','.join(ctx.validation.steps_passed)}")
    return " ".join(parts)
