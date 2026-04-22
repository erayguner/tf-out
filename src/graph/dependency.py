"""Dependency graph builder.

Extracts three classes of dependency from the discovered resource attributes:
  1. Structural: subnet -> network, instance -> subnet/network/disk, etc.
  2. IAM:        binding -> service account (when the member is a GCP SA).
  3. Location:   resources in a project depend on the project existing.

Implicit TF references (HCL interpolations) encode most of this automatically
when generation is extended to emit `.id` references. For now the graph is the
source of truth that validates the IaC made sense and feeds visualisation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from ..discovery.models import DiscoveredResource

log = logging.getLogger(__name__)


@dataclass
class DependencyGraph:
    graph: nx.DiGraph

    def to_json(self) -> dict:
        return {
            "nodes": [{"id": n, **self.graph.nodes[n]} for n in self.graph.nodes],
            "edges": [{"from": u, "to": v, **self.graph.edges[u, v]} for u, v in self.graph.edges],
        }

    def to_dot(self) -> str:
        lines = ["digraph dependencies {", "  rankdir=LR;", "  node [shape=box];"]
        for n, attrs in self.graph.nodes(data=True):
            label = f"{attrs.get('domain', '?')}\\n{attrs.get('name', n)}"
            lines.append(f'  "{n}" [label="{label}"];')
        for u, v, attrs in self.graph.edges(data=True):
            kind = attrs.get("kind", "")
            lines.append(f'  "{u}" -> "{v}" [label="{kind}"];')
        lines.append("}")
        return "\n".join(lines)

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "graph.json").write_text(json.dumps(self.to_json(), indent=2))
        (out_dir / "graph.dot").write_text(self.to_dot())
        log.info("Dependency graph written to %s", out_dir)


def build_graph(resources: Iterable[DiscoveredResource]) -> DependencyGraph:
    g = nx.DiGraph()
    by_name: dict[str, DiscoveredResource] = {r.full_resource_name: r for r in resources}
    by_short: dict[str, DiscoveredResource] = {r.name: r for r in resources}

    # Nodes
    for r in by_name.values():
        g.add_node(
            r.stable_id(),
            asset_type=r.asset_type,
            domain=r.domain,
            name=r.name,
            full_resource_name=r.full_resource_name,
        )

    # Edges — structural
    for r in by_name.values():
        _add_structural_edges(g, r, by_name, by_short)
        _add_iam_edges(g, r, by_name, by_short)

    # Cycle check — rare in infra but fatal for TF order
    cycles = list(nx.simple_cycles(g))
    if cycles:
        log.warning("Dependency cycles detected: %s", cycles)

    return DependencyGraph(graph=g)


# ---- edge extractors ---------------------------------------------------------


def _add_structural_edges(g, r, by_name, by_short) -> None:
    a = r.attributes
    src = r.stable_id()

    def link(target_key: str | None, kind: str) -> None:
        if not target_key:
            return
        target = by_name.get(target_key) or by_short.get(_short_of(target_key))
        if target:
            g.add_edge(src, target.stable_id(), kind=kind)

    if r.asset_type == "compute.googleapis.com/Subnetwork":
        link(a.get("network"), "subnet->network")

    elif r.asset_type == "compute.googleapis.com/Firewall":
        link(a.get("network"), "firewall->network")

    elif r.asset_type == "compute.googleapis.com/Route":
        link(a.get("network"), "route->network")

    elif r.asset_type == "compute.googleapis.com/Instance":
        for nic in a.get("networkInterfaces") or []:
            link(nic.get("network"), "instance->network")
            link(nic.get("subnetwork"), "instance->subnet")
        for disk in a.get("disks") or []:
            link(disk.get("source"), "instance->disk")


def _add_iam_edges(g, r, by_name, by_short) -> None:
    policy = r.attributes.get("iam_policy")
    if not policy:
        return
    src = r.stable_id()
    for binding in policy.get("bindings", []):
        for member in binding.get("members", []):
            if not member.startswith("serviceAccount:"):
                continue
            sa_email = member.split(":", 1)[1]
            # Match by email attribute since CAI returns SA objects with .email
            for candidate in by_name.values():
                if (
                    candidate.asset_type == "iam.googleapis.com/ServiceAccount"
                    and candidate.attributes.get("email") == sa_email
                ):
                    g.add_edge(src, candidate.stable_id(), kind=f"iam:{binding['role']}")
                    break


def _short_of(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]
