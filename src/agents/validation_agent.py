"""Validation Agent — runs the sandbox lifecycle. No output is 'done' without this."""

from __future__ import annotations

import logging

from ..settings import Settings
from ..validation.sandbox import SandboxLifecycle

log = logging.getLogger(__name__)


class ValidationAgent:
    name = "validation"

    def __init__(self, settings: Settings):
        self._s = settings

    def run(self, ctx):
        if not ctx.output_dir:
            raise RuntimeError("validation requires an output directory")

        v = self._s.validation
        if not v.sandbox_project_id:
            ctx.audit.record(
                self.name,
                "skipped",
                str(ctx.output_dir),
                "denied",
                rationale="sandbox_project_id not configured",
            )
            raise RuntimeError("validation.sandbox_project_id is required but missing")

        # HITL gate on sandbox apply (automated-yes in CI via AI_TF_APPROVE=yes)
        if v.auto_apply:
            approval = ctx.hitl.request(
                "sandbox_apply",
                f"Will terraform apply {ctx.output_dir} against project {v.sandbox_project_id} and destroy after.",
                run_id=ctx.audit.run_id,
            )
            ctx.audit.record(
                self.name,
                "hitl_decision",
                "sandbox_apply",
                "approved" if approval.granted else "denied",
                rationale=approval.reason,
                approver=approval.approver,
            )
            if not approval.granted:
                raise RuntimeError("sandbox apply denied by HITL")

        lifecycle = SandboxLifecycle(
            working_dir=ctx.output_dir,
            sandbox_project_id=v.sandbox_project_id,
            discovery_scope=self._s.project.scope_id,
            region=v.sandbox_region,
            apply_timeout=v.apply_timeout_seconds,
        )
        result = lifecycle.validate_and_apply()
        ctx.validation = result

        ctx.audit.record(
            self.name,
            "sandbox_run",
            v.sandbox_project_id,
            "success" if result.fully_validated else "failure",
            rationale=f"steps_passed={result.steps_passed}",
            steps_passed=result.steps_passed,
        )
        return ctx
