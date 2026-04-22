from pathlib import Path

from src.core.agent_trace import AgentTrace, StepKind, new_trace


def test_steps_preserve_parent_chain():
    t = new_trace()
    root = t.new_step(StepKind.TOOL, "discovery", "cai_inventory")
    child = t.new_step(StepKind.TOOL, "discovery", "cai_iam_policies", parent=root)
    assert child.parent_step_id == root.step_id
    assert child.correlation_id == t.correlation_id == root.correlation_id


def test_trace_writes_and_loads(tmp_path: Path):
    t = new_trace()
    s = t.new_step(StepKind.POLICY, "gov", "deny_public_iam", rationale="scanned bindings")
    t.close_step(s, verdict="allow")
    t.close()
    p = t.write(tmp_path)
    reloaded = AgentTrace.load(p)
    assert reloaded.correlation_id == t.correlation_id
    assert reloaded.steps[0].verdict == "allow"


def test_otel_emission_has_span_fields():
    t = new_trace()
    s = t.new_step(StepKind.TOOL, "val", "terraform_plan")
    t.close_step(s, verdict="allow")
    spans = t.to_otel_spans()
    assert spans and spans[0]["trace_id"] == t.correlation_id
    assert spans[0]["span_id"] == s.step_id
    assert spans[0]["name"] == "tool.terraform_plan"


def test_replay_produces_markdown():
    t = new_trace()
    s = t.new_step(StepKind.TOOL, "disc", "cai", rationale="scan 42 types")
    t.close_step(s, verdict="allow")
    md = t.replay()
    assert "# Agent trace" in md
    assert "tool · disc · cai" in md
    assert "scan 42 types" in md
