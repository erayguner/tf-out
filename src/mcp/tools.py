"""MCP tool surface.

Every agent step is reachable as an MCP tool so external orchestrators (or
Claude Code) can call them individually. Each tool declares a JSONSchema-like
shape and returns structured JSON — no free-form prose.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from ..agents.orchestrator import PipelineContext, run_pipeline
from ..governance import AuditLog, HumanGate
from ..settings import load as load_settings


@dataclass
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]


def _run(args: dict) -> dict:
    cfg_path = args.get("config_path", "config/settings.yaml")
    non_interactive = bool(args.get("non_interactive", True))
    s = load_settings(cfg_path)
    audit = AuditLog(s.governance.audit_log_dir)
    hitl = HumanGate(interactive=not non_interactive)
    ctx = PipelineContext(settings=s, audit=audit, hitl=hitl)
    result = run_pipeline(ctx)
    return {
        "success": result.success,
        "message": result.message,
        "run_id": audit.run_id,
        "audit_log": str(audit.path),
        "output_dir": str(ctx.output_dir) if ctx.output_dir else None,
        "discovered": len(ctx.discovery.resources) if ctx.discovery else 0,
        "violations": [asdict(v) for v in ctx.violations],
        "validation_steps": ctx.validation.steps_passed if ctx.validation else [],
    }


MCP_TOOLS: list[ToolDescriptor] = [
    ToolDescriptor(
        name="ai_tf_run_pipeline",
        description="Run the full discovery -> generate -> sandbox-validate pipeline.",
        input_schema={
            "type": "object",
            "properties": {
                "config_path": {"type": "string"},
                "non_interactive": {"type": "boolean"},
            },
        },
        handler=_run,
    ),
]


def register_tools(server) -> None:
    """Register tools with an MCP server instance (adapter-agnostic)."""
    for t in MCP_TOOLS:
        server.add_tool(t.name, t.description, t.input_schema, t.handler)
