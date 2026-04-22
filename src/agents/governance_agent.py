"""Governance Agent — runs policy engine + HITL approval.

Sits AFTER classification (so it can see what's being generated) and BEFORE
generation (so deny verdicts abort the run before any file is written).
"""

from __future__ import annotations

import logging

from ..governance.policies import PolicyEngine
from ..settings import Settings

log = logging.getLogger(__name__)


class GovernanceAgent:
    name = "governance"

    def __init__(self, settings: Settings, engine: PolicyEngine):
        self._s = settings
        self._engine = engine

    def run(self, ctx):
        violations = self._engine.evaluate(ctx.classified)
        ctx.violations = violations
        blocking = self._engine.blocking(violations)

        for v in violations:
            ctx.audit.record(
                self.name,
                "policy_violation",
                v.resource,
                "denied" if v.severity == "deny" else "warning",
                rationale=f"{v.rule}: {v.detail}",
                rule=v.rule,
                severity=v.severity,
            )

        if blocking:
            # HITL can waive deny with an explicit approval
            summary = "\n".join(f"  - {v.rule}: {v.resource} ({v.detail})" for v in blocking)
            approval = ctx.hitl.request(
                "override_policy_deny",
                f"{len(blocking)} blocking policy violation(s):\n{summary}",
                run_id=ctx.audit.run_id,
            )
            ctx.audit.record(
                self.name,
                "hitl_decision",
                "override_policy_deny",
                "approved" if approval.granted else "denied",
                rationale=approval.reason,
                approver=approval.approver,
            )
            if not approval.granted:
                raise RuntimeError(f"Policy denied: {len(blocking)} blocking violations")

        return ctx
