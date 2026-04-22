"""Pipeline orchestrator.

Each agent exposes ``run(ctx) -> ctx``. The orchestrator runs them sequentially
and records every step in the audit log. When ``google-adk`` is installed the
same agents expose ADK-compatible tool wrappers (see ``adk_bridge.py``) — the
orchestration here is deliberately framework-independent so tests don't need
an LLM runtime.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..discovery.classifiers import Classified
from ..discovery.models import DiscoveryReport
from ..governance.audit import AuditLog
from ..governance.hitl import HumanGate
from ..governance.policies import PolicyEngine, PolicyViolation
from ..graph.dependency import DependencyGraph
from ..settings import Settings
from ..validation.sandbox import SandboxResult
from .classification_agent import ClassificationAgent
from .dependency_agent import DependencyAgent
from .discovery_agent import DiscoveryAgent
from .governance_agent import GovernanceAgent
from .reasoning_bank_agent import ReasoningBankAgent
from .terraform_agent import TerraformAgent
from .validation_agent import ValidationAgent

log = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    settings: Settings
    audit: AuditLog
    hitl: HumanGate

    # Populated as the pipeline runs
    discovery: DiscoveryReport | None = None
    classified: list[Classified] = field(default_factory=list)
    violations: list[PolicyViolation] = field(default_factory=list)
    output_dir: Path | None = None
    graph: DependencyGraph | None = None
    validation: SandboxResult | None = None
    # Optional prior-run context (populated when memory.enabled)
    prior_runs: list[dict] = field(default_factory=list)


@dataclass
class PipelineResult:
    context: PipelineContext
    success: bool
    message: str


Agent = Callable[[PipelineContext], PipelineContext]


def build_pipeline(settings: Settings) -> list[Agent]:
    """Return the ordered sequence of agents that form the pipeline."""
    reasoning_bank = ReasoningBankAgent(settings)

    def hydrate_prior_runs(ctx):
        if settings.memory.enabled and ctx.discovery:
            query = (
                f"scope={settings.project.scope_id} env={settings.project.environment} "
                f"resources={len(ctx.discovery.resources)}"
            )
            ctx.prior_runs = reasoning_bank.similar_runs(query, k=5)
            ctx.audit.record(
                "reasoning_bank",
                "similar_runs_loaded",
                settings.project.scope_id,
                "success",
                rationale=f"found {len(ctx.prior_runs)} prior trajectories",
                count=len(ctx.prior_runs),
            )
        return ctx

    return [
        DiscoveryAgent(settings).run,
        ClassificationAgent(settings).run,
        hydrate_prior_runs,
        GovernanceAgent(settings, PolicyEngine(settings.governance)).run,
        TerraformAgent(settings).run,
        DependencyAgent(settings).run,
        ValidationAgent(settings).run,
        reasoning_bank.run,  # tail: persist the trajectory
    ]


def run_pipeline(ctx: PipelineContext) -> PipelineResult:
    for step in build_pipeline(ctx.settings):
        try:
            ctx = step(ctx)
        except Exception as exc:
            log.exception("Pipeline step failed")
            ctx.audit.record(
                actor="orchestrator",
                action="step_failed",
                target=step.__qualname__,
                outcome="failure",
                rationale=str(exc),
            )
            return PipelineResult(ctx, False, f"{step.__qualname__}: {exc}")

    ok = bool(ctx.validation and ctx.validation.fully_validated)
    return PipelineResult(
        ctx,
        ok,
        "All stages passed sandbox validation" if ok else "Pipeline completed with validation gaps",
    )
