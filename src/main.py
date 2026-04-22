"""tf-out CLI entry point."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import settings as settings_mod
from .agents.orchestrator import PipelineContext, run_pipeline
from .governance import AuditLog, HumanGate

app = typer.Typer(help="Google ADK agentic GCP discovery + Terraform generation")
console = Console()


@app.command()
def run(
    config: Path = typer.Option(Path("config/settings.yaml"), help="Settings YAML"),
    non_interactive: bool = typer.Option(False, help="Force non-interactive HITL (reads AI_TF_APPROVE)"),
    log_level: str = typer.Option("INFO"),
) -> None:
    """Run the full discovery -> generate -> validate pipeline."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    s = settings_mod.load(config)
    audit = AuditLog(s.governance.audit_log_dir)
    hitl = HumanGate(interactive=False if non_interactive else None)

    console.print(f"[bold]tf-out[/bold] run_id={audit.run_id} scope={s.project.scope_id}")

    ctx = PipelineContext(settings=s, audit=audit, hitl=hitl)
    result = run_pipeline(ctx)

    _render_summary(result)
    sys.exit(0 if result.success else 1)


@app.command()
def inspect(config: Path = typer.Option(Path("config/settings.yaml"))) -> None:
    """Print settings and exit. Useful for CI smoke tests."""
    s = settings_mod.load(config)
    console.print_json(data=s.model_dump())


def _render_summary(result) -> None:
    ctx = result.context
    t = Table(title=f"Pipeline run ({'OK' if result.success else 'FAILED'})")
    t.add_column("Stage")
    t.add_column("Outcome")

    t.add_row("discovery", f"{len(ctx.discovery.resources)} resources" if ctx.discovery else "—")
    t.add_row("classification", f"{len(ctx.classified)} classified")
    t.add_row("governance", f"{len(ctx.violations)} violations")
    t.add_row("generation", str(ctx.output_dir) if ctx.output_dir else "—")
    t.add_row(
        "graph",
        f"{ctx.graph.graph.number_of_nodes()} nodes, {ctx.graph.graph.number_of_edges()} edges" if ctx.graph else "—",
    )
    if ctx.validation:
        t.add_row("validation", ",".join(ctx.validation.steps_passed))
    else:
        t.add_row("validation", "—")

    console.print(t)
    console.print(f"Audit log: {ctx.audit.path}")
    console.print(f"[dim]{result.message}[/dim]")


if __name__ == "__main__":
    app()
