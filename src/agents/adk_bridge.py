"""ADK bridge — exposes the deterministic pipeline as a Google ADK agent.

The pipeline's Python stages (see ``orchestrator.py``) pass a rich in-memory
``PipelineContext`` between each other. That context is not JSON-schema
serialisable, so it cannot be exposed directly as ADK ``FunctionTool``
parameters. Instead we expose the *entire* pipeline as one deterministic tool
and let a small ``LlmAgent`` drive it and write the human-facing summary.

Importing this module is optional. If ``google-adk`` isn't installed the
orchestrator in ``orchestrator.py`` works standalone.
"""

from __future__ import annotations

import logging
from typing import Any

from ..settings import Settings

log = logging.getLogger(__name__)

try:
    from google.adk.agents import LlmAgent
    from google.adk.tools import FunctionTool
except ImportError:  # pragma: no cover — optional dep
    LlmAgent = FunctionTool = None  # type: ignore[assignment]


def build_adk_root(settings: Settings) -> Any:
    """Return the ADK root agent, or raise if the SDK isn't installed.

    The returned ``LlmAgent`` has a single tool, ``run_ai_tf_pipeline``, which
    runs the full discovery → classification → governance → generation →
    validation pipeline and returns a structured summary. The model's job is
    only to call the tool and narrate the result for a human reviewer.
    """
    if LlmAgent is None:
        raise ImportError("google-adk is not installed. `pip install google-adk` to use the ADK runtime.")

    # Local imports keep optional-dep surface out of the module top level
    from ..governance.audit import AuditLog
    from ..governance.hitl import HumanGate
    from .orchestrator import PipelineContext, run_pipeline

    def run_ai_tf_pipeline() -> dict:
        """Run the tf-out pipeline and return a JSON-serialisable summary.

        Always non-interactive — HITL approvals come from env vars
        (see runbook: "Approving out of band").
        """
        audit = AuditLog(settings.governance.audit_log_dir)
        hitl = HumanGate(interactive=False)
        ctx = PipelineContext(settings=settings, audit=audit, hitl=hitl)
        result = run_pipeline(ctx)
        return {
            "success": result.success,
            "message": result.message,
            "run_id": audit.run_id,
            "audit_log": str(audit.path),
            "resources": len(ctx.discovery.resources) if ctx.discovery else 0,
            "classified": len(ctx.classified),
            "violations": len(ctx.violations),
            "output_dir": str(ctx.output_dir) if ctx.output_dir else None,
            "validation_steps_passed": (list(ctx.validation.steps_passed) if ctx.validation else []),
        }

    return LlmAgent(
        name="ai_tf_root",
        model="gemini-2.5-pro",
        instruction=(
            "You orchestrate the tf-out pipeline. Call run_ai_tf_pipeline() "
            "exactly once, then summarise the result for a human reviewer. "
            "Cite which resources were imported vs generated-fresh, list any "
            "policy violations, report the audit log path, and flag anomalies. "
            "Do not re-run the pipeline; do not invent additional tool calls."
        ),
        tools=[FunctionTool(run_ai_tf_pipeline)],
    )
