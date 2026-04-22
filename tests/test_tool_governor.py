from pathlib import Path

from src.core.tool_governor import (
    BudgetLimits,
    GovernancePolicy,
    ToolCategory,
    ToolDecision,
    ToolGovernor,
    ToolRequest,
)
from src.governance.audit import AuditLog


def _gov(tmp_path: Path, **over):
    audit = AuditLog(tmp_path)
    policy = GovernancePolicy(
        allow=over.pop("allow", {"read_thing"}),
        deny=over.pop("deny", set()),
        require_approval=over.pop("require_approval", set()),
        category_allow=over.pop("category_allow", {ToolCategory.DISCOVERY}),
        budgets=over.pop("budgets", BudgetLimits(max_calls=3, max_calls_per_tool=2, max_wall_seconds=60)),
        default_allow=over.pop("default_allow", False),
    )
    return ToolGovernor(policy, audit, halt_check=over.pop("halt_check", lambda: (False, ""))), audit


def test_allowed_tool_runs(tmp_path: Path):
    gov, _ = _gov(tmp_path)
    r = gov.governed_call(
        ToolRequest("read_thing", ToolCategory.DISCOVERY),
        invoke=lambda: 42,
    )
    assert r.decision == ToolDecision.ALLOW
    assert r.value == 42


def test_unknown_tool_denied_fail_closed(tmp_path: Path):
    gov, _ = _gov(tmp_path)
    r = gov.governed_call(
        ToolRequest("unknown_tool", ToolCategory.EXECUTION),
        invoke=lambda: "should not run",
    )
    assert r.decision == ToolDecision.DENY
    assert "fail-closed" in r.reason


def test_require_approval_short_circuits(tmp_path: Path):
    gov, _ = _gov(tmp_path, allow={"sensitive_op"}, require_approval={"sensitive_op"})
    r = gov.governed_call(
        ToolRequest("sensitive_op", ToolCategory.DISCOVERY),
        invoke=lambda: "should not run",
    )
    assert r.decision == ToolDecision.APPROVAL_REQUIRED


def test_budget_enforced(tmp_path: Path):
    gov, _ = _gov(tmp_path, budgets=BudgetLimits(max_calls=2, max_calls_per_tool=10, max_wall_seconds=60))
    for _ in range(2):
        r = gov.governed_call(ToolRequest("read_thing", ToolCategory.DISCOVERY), invoke=lambda: 1)
        assert r.decision == ToolDecision.ALLOW
    # Third call blocked by global budget
    r = gov.governed_call(ToolRequest("read_thing", ToolCategory.DISCOVERY), invoke=lambda: 1)
    assert r.decision == ToolDecision.DENY
    assert "budget" in r.reason


def test_kill_switch_halts(tmp_path: Path):
    gov, _ = _gov(tmp_path, halt_check=lambda: (True, "operator-requested"))
    r = gov.governed_call(ToolRequest("read_thing", ToolCategory.DISCOVERY), invoke=lambda: "noop")
    assert r.decision == ToolDecision.HALT
    assert "operator-requested" in r.reason


def test_filter_blocks_tool_call_on_secret(tmp_path: Path):
    gov, _ = _gov(tmp_path)
    r = gov.governed_call(
        ToolRequest("read_thing", ToolCategory.DISCOVERY, args={"token": "ghp_" + "a" * 40}),
        invoke=lambda: "should not run",
    )
    assert r.decision == ToolDecision.DENY
    assert any(f["detector"] == "github_pat" for f in r.filter_findings)
