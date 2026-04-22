"""Dependency Mapping Agent — builds + persists the resource graph."""

from __future__ import annotations

import logging
from pathlib import Path

from ..graph import build_graph
from ..settings import Settings

log = logging.getLogger(__name__)


class DependencyAgent:
    name = "dependency"

    def __init__(self, settings: Settings):
        self._s = settings

    def run(self, ctx):
        if not ctx.discovery or not ctx.output_dir:
            raise RuntimeError("dependency step requires discovery + output_dir")

        graph = build_graph(ctx.discovery.resources)
        ctx.graph = graph
        graph.write(Path(ctx.output_dir))

        ctx.audit.record(
            self.name,
            "graph_built",
            str(ctx.output_dir),
            "success",
            rationale=f"nodes={graph.graph.number_of_nodes()} edges={graph.graph.number_of_edges()}",
            nodes=graph.graph.number_of_nodes(),
            edges=graph.graph.number_of_edges(),
        )
        return ctx
