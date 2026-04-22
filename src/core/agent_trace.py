"""AgentTrace model (§9.1).

One ``AgentTrace`` per session. Every model invocation, tool call, guardrail
verdict, approval decision, and human override becomes an ``AgentStep`` with:

* ``step_id``         — unique within the trace
* ``parent_step_id``  — the step that caused this one
* ``correlation_id``  — the trace-level ID (== session id); maps to OTel trace_id

OTel-compatible: ``to_otel_spans()`` emits OTLP-shaped dicts a vendor exporter
can ship to Cloud Trace / Datadog / Honeycomb.

Persistence: traces are serialised as JSON next to the audit log, so
``replay(session_id)`` reconstructs the full transcript deterministically.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any


class StepKind(str, Enum):
    MODEL = "model"
    TOOL = "tool"
    GUARDRAIL = "guardrail"
    APPROVAL = "approval"
    HUMAN_OVERRIDE = "human_override"
    POLICY = "policy"
    FILTER = "filter"


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class AgentStep:
    step_id: str
    correlation_id: str
    kind: StepKind
    actor: str
    name: str  # tool/model/policy name
    started_at: str
    ended_at: str | None = None
    parent_step_id: str | None = None
    rationale: str = ""  # §10.1 — required for every step
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    verdict: str | None = None  # allow/deny/approve/halt
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class HumanOverrideStep(AgentStep):
    approver: str = ""
    channel: str = ""  # cli | webhook | chat


@dataclass
class AgentTrace:
    correlation_id: str
    started_at: str = field(default_factory=_utcnow_iso)
    ended_at: str | None = None
    steps: list[AgentStep] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)

    # ---- builders -----------------------------------------------------

    def new_step(
        self,
        kind: StepKind,
        actor: str,
        name: str,
        *,
        parent: AgentStep | None = None,
        rationale: str = "",
        **inputs: Any,
    ) -> AgentStep:
        step = AgentStep(
            step_id=uuid.uuid4().hex,
            correlation_id=self.correlation_id,
            kind=kind,
            actor=actor,
            name=name,
            started_at=_utcnow_iso(),
            parent_step_id=parent.step_id if parent else None,
            rationale=rationale,
            inputs=inputs or {},
        )
        self.steps.append(step)
        return step

    def close_step(self, step: AgentStep, verdict: str | None = None, **outputs: Any) -> AgentStep:
        step.ended_at = _utcnow_iso()
        step.verdict = verdict
        if outputs:
            step.outputs.update(outputs)
        return step

    def close(self) -> None:
        self.ended_at = _utcnow_iso()

    # ---- persistence --------------------------------------------------

    def write(self, directory: str | Path) -> Path:
        p = Path(directory) / f"{self.correlation_id}.trace.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, default=_json_default))
        return p

    @classmethod
    def load(cls, path: str | Path) -> AgentTrace:
        data = json.loads(Path(path).read_text())
        steps = [AgentStep(**{**s, "kind": StepKind(s["kind"])}) for s in data.pop("steps")]
        return cls(**data, steps=steps)

    # ---- replay (§9.3) ------------------------------------------------

    def replay(self) -> str:
        """Return a Markdown transcript suitable for a review document."""
        lines = [f"# Agent trace `{self.correlation_id}`", f"Started: {self.started_at}"]
        for s in self.steps:
            lines.append(f"\n## {s.kind.value} · {s.actor} · {s.name}")
            lines.append(f"*{s.started_at}* → *{s.ended_at}*  verdict=**{s.verdict or '—'}**")
            if s.rationale:
                lines.append(f"> {s.rationale}")
            if s.inputs:
                lines.append(f"- inputs: `{json.dumps(s.inputs, default=_json_default)[:200]}`")
            if s.outputs:
                lines.append(f"- outputs: `{json.dumps(s.outputs, default=_json_default)[:200]}`")
        if self.ended_at:
            lines.append(f"\nEnded: {self.ended_at}")
        return "\n".join(lines)

    # ---- OpenTelemetry emission (§9.1) --------------------------------

    def to_otel_spans(self) -> list[dict[str, Any]]:
        spans = []
        for s in self.steps:
            spans.append(
                {
                    "trace_id": self.correlation_id,
                    "span_id": s.step_id,
                    "parent_span_id": s.parent_step_id,
                    "name": f"{s.kind.value}.{s.name}",
                    "start_time": s.started_at,
                    "end_time": s.ended_at,
                    "attributes": {
                        "actor": s.actor,
                        "rationale": s.rationale,
                        "verdict": s.verdict or "",
                        **s.attributes,
                    },
                }
            )
        return spans


def _json_default(o):
    if isinstance(o, Enum):
        return o.value
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def new_trace() -> AgentTrace:
    return AgentTrace(correlation_id=uuid.uuid4().hex)
