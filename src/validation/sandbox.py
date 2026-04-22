"""Sandbox lifecycle controller.

The sandbox project is an isolated GCP project that exists solely to prove
that the generated HCL applies cleanly. Day-one requirement: apply + destroy
is automated with a hard timeout and a guaranteed teardown.

Safety rails:
  * Refuses to run if the sandbox project ID matches the discovery scope
  * Always issues ``terraform destroy`` in a try/finally so nothing leaks
  * Ceiling on apply timeout — settable from config
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .runner import TerraformResult, TerraformRunner

log = logging.getLogger(__name__)


class SandboxViolation(RuntimeError):
    """Raised when the sandbox invariant is about to be broken."""


@dataclass
class SandboxResult:
    init: TerraformResult | None = None
    validate: TerraformResult | None = None
    plan: TerraformResult | None = None
    apply: TerraformResult | None = None
    destroy: TerraformResult | None = None
    steps_passed: list[str] = field(default_factory=list)

    @property
    def fully_validated(self) -> bool:
        return {"init", "validate", "plan", "apply", "destroy"}.issubset(set(self.steps_passed))


class SandboxLifecycle:
    def __init__(
        self,
        working_dir: str | Path,
        sandbox_project_id: str,
        discovery_scope: str,
        region: str = "us-central1",
        apply_timeout: int = 600,
        generate_config: bool = True,
    ):
        if not sandbox_project_id:
            raise SandboxViolation("sandbox_project_id is required")
        if sandbox_project_id in discovery_scope:
            raise SandboxViolation(
                f"Refusing to run: sandbox project {sandbox_project_id!r} is inside "
                f"discovery scope {discovery_scope!r}. Use a dedicated empty project."
            )
        self._runner = TerraformRunner(
            working_dir,
            extra_env={
                "TF_VAR_project_id": sandbox_project_id,
                "TF_VAR_region": region,
            },
        )
        self._timeout = apply_timeout
        self._generate_config = generate_config
        self._working_dir = Path(working_dir)

    def _needs_generate_config(self) -> bool:
        """Heuristic: if GENERATE_CONFIG.md exists the writer flagged
        import-only resources that need Terraform to synthesise their HCL."""
        return (self._working_dir / "GENERATE_CONFIG.md").exists()

    def validate_and_apply(self) -> SandboxResult:
        """Full init -> validate -> plan -> apply -> destroy cycle."""
        result = SandboxResult()

        result.init = self._runner.init()
        if not result.init.ok:
            return result
        result.steps_passed.append("init")

        result.validate = self._runner.validate()
        if not result.validate.ok:
            return result
        result.steps_passed.append("validate")

        # If the working dir contains import blocks for resources without
        # matching HCL (the import-only tier in classifiers.REGISTRY), run
        # `plan -generate-config-out` first so Terraform synthesises those
        # resource blocks. Terraform 1.5+ prescribed flow.
        if self._generate_config and self._needs_generate_config():
            gen = self._runner.plan_generate_config("auto_generated.tf")
            # A non-zero exit here is OK: generate-config-out sometimes exits
            # with code 2 (changes present). Only a hard error (non-0, non-2)
            # is fatal — we'll let the next `plan` catch real problems.
            if gen.exit_code not in (0, 2):
                result.plan = gen
                return result

        result.plan = self._runner.plan()
        if not result.plan.ok:
            return result
        result.steps_passed.append("plan")

        try:
            result.apply = self._runner.apply(timeout=self._timeout)
            if result.apply.ok:
                result.steps_passed.append("apply")
        finally:
            # Destroy ALWAYS runs. A failed apply can leave partial state.
            result.destroy = self._runner.destroy(timeout=self._timeout)
            if result.destroy.ok:
                result.steps_passed.append("destroy")

        return result
