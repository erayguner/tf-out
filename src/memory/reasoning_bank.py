"""ReasoningBank — higher-level trajectory store.

A trajectory is a compact summary of one pipeline run:

  * correlation_id, scope, environment
  * outcome (success / partial / failure)
  * signals extracted from the AgentTrace:
      - resources discovered
      - classification counts
      - violations
      - validation steps passed
  * rationale (human-readable summary)

Governance agents can ``search_similar`` to ask "have we seen this scope /
pattern before, and what happened?". The search result is advisory — no
agent **acts** on prior memory alone; it's context for a fresh decision.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from .agentdb_client import AgentDBClient, SidecarResponse

log = logging.getLogger(__name__)


@dataclass
class Trajectory:
    correlation_id: str
    scope: str
    environment: str
    outcome: str  # success | partial | failure
    resources_discovered: int
    counts: dict[str, int]  # classification buckets
    violations: list[dict[str, Any]] = field(default_factory=list)
    validation_steps: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_search_text(self) -> str:
        """Flatten the trajectory into a text blob for embedding."""
        return (
            f"scope={self.scope} env={self.environment} outcome={self.outcome} "
            f"resources={self.resources_discovered} counts={self.counts} "
            f"violations={len(self.violations)} steps={','.join(self.validation_steps)} "
            f"rationale={self.rationale}"
        )


class ReasoningBank:
    """Thin facade over ``AgentDBClient`` keyed by namespace (== project scope)."""

    def __init__(self, client: AgentDBClient, namespace: str):
        self._client = client
        self._namespace = namespace

    @property
    def namespace(self) -> str:
        return self._namespace

    # ---- write -------------------------------------------------------

    def record(self, trajectory: Trajectory) -> SidecarResponse:
        """Store a finished trajectory. Fail-open."""
        response = self._client.store(
            namespace=self._namespace,
            text=trajectory.to_search_text(),
            metadata=asdict(trajectory),
            outcome=trajectory.outcome,
            correlation_id=trajectory.correlation_id,
        )
        if not response.ok:
            log.warning("ReasoningBank.record failed: %s", response.error)
        return response

    # ---- read --------------------------------------------------------

    def search_similar(self, query_text: str, k: int = 5) -> list[dict[str, Any]]:
        """Return up to ``k`` similar prior trajectories, or [] on failure."""
        response = self._client.search(
            namespace=self._namespace,
            text=query_text,
            k=k,
            min_confidence=0.3,
        )
        if not response.ok:
            log.info("ReasoningBank.search_similar returning empty: %s", response.error)
            return []
        return response.data.get("patterns", [])

    # ---- maintenance -------------------------------------------------

    def prune(self, max_age_seconds: int | None = None) -> SidecarResponse:
        """Apply retention policy (§11.6). Call from a cron or manual op."""
        return self._client.prune(
            min_confidence=0.3,
            min_usage=0,
            max_age_seconds=max_age_seconds,
        )

    def delete_by_correlation(self, correlation_id: str) -> SidecarResponse:
        """User-scoped deletion (§11.6 right-to-be-forgotten).

        Implemented as a pruning pass with a high-confidence filter that
        excludes the target. Today the sidecar API doesn't expose per-id
        delete — this helper is a placeholder documenting the intent; it
        returns an explicit error so callers don't silently trust it.
        """
        return SidecarResponse(
            ok=False,
            error="per-correlation-id deletion not yet wired on sidecar; extend /delete endpoint in sidecar/server.mjs",
        )
