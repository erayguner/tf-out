"""Tool governor — single enforcement point (§4.1).

Every tool call — internal pipeline stage, MCP tool invocation, provider API
call — funnels through ``ToolGovernor.governed_call``. The governor:

1. Verifies the tool is allow-listed (fail-closed default).
2. Checks the category budget (per-tool and overall call caps).
3. Checks a kill-switch halt flag (§14.1).
4. Runs the content filter stack against the ``ToolRequest.args``.
5. Executes the wrapped callable, capturing latency + result.
6. Emits an audit record for the decision + outcome.

No tool call bypasses it. Calling the underlying function directly is a
policy violation caught by code review (boundary contracts list governed
callables only).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..governance.audit import AuditLog
from .filters import FilterStack

log = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    DISCOVERY = "discovery"  # read-only inventory
    CONNECTION = "connection"  # auth / credential ops
    EXECUTION = "execution"  # mutating actions (terraform apply etc.)
    OTHER = "other"


class ToolDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"
    HALT = "halt"


@dataclass
class BudgetLimits:
    max_calls: int = 1000
    max_calls_per_tool: int = 500
    max_wall_seconds: int = 3600
    max_parallelism: int = 1  # MVP is serial; L2 may raise


@dataclass
class GovernancePolicy:
    # Fail-closed: a tool not in ``allow`` is denied
    allow: set[str] = field(default_factory=set)
    deny: set[str] = field(default_factory=set)
    require_approval: set[str] = field(default_factory=set)
    category_allow: set[ToolCategory] = field(default_factory=lambda: {ToolCategory.DISCOVERY})
    budgets: BudgetLimits = field(default_factory=BudgetLimits)
    default_allow: bool = False  # MUST stay False in production


@dataclass
class ToolRequest:
    tool_name: str
    category: ToolCategory
    args: dict[str, Any] = field(default_factory=dict)
    principal: str = "pipeline"
    rationale: str = ""


@dataclass
class ToolResult:
    decision: ToolDecision
    tool_name: str
    value: Any = None
    duration_ms: float = 0.0
    error: str = ""
    filter_findings: list[dict] = field(default_factory=list)
    reason: str = ""


class ToolGovernor:
    def __init__(
        self,
        policy: GovernancePolicy,
        audit: AuditLog,
        *,
        filters: FilterStack | None = None,
        halt_check: Callable[[], tuple[bool, str]] | None = None,
    ):
        self._policy = policy
        self._audit = audit
        self._filters = filters or FilterStack()
        self._halt_check = halt_check or (lambda: (False, ""))
        self._started_at = time.monotonic()
        self._call_count = 0
        self._per_tool: dict[str, int] = {}

    def governed_call(self, request: ToolRequest, invoke: Callable[[], Any]) -> ToolResult:
        started = time.monotonic()

        # 1) halt-check — kill-switch
        halted, halt_reason = self._halt_check()
        if halted:
            return self._finalise(request, ToolDecision.HALT, started, reason=f"kill-switch: {halt_reason}")

        # 2) allow-list / deny-list / approval-required
        if request.tool_name in self._policy.deny:
            return self._finalise(request, ToolDecision.DENY, started, reason="explicit deny-list")
        allow_by_name = request.tool_name in self._policy.allow
        allow_by_category = request.category in self._policy.category_allow
        if not (allow_by_name or allow_by_category or self._policy.default_allow):
            return self._finalise(request, ToolDecision.DENY, started, reason="not in allow-list (fail-closed)")

        if request.tool_name in self._policy.require_approval:
            return self._finalise(request, ToolDecision.APPROVAL_REQUIRED, started, reason="approval required")

        # 3) budgets
        if self._call_count >= self._policy.budgets.max_calls:
            return self._finalise(request, ToolDecision.DENY, started, reason="global call budget exhausted")
        if self._per_tool.get(request.tool_name, 0) >= self._policy.budgets.max_calls_per_tool:
            return self._finalise(
                request, ToolDecision.DENY, started, reason=f"per-tool budget for {request.tool_name} exhausted"
            )
        if time.monotonic() - self._started_at > self._policy.budgets.max_wall_seconds:
            return self._finalise(request, ToolDecision.DENY, started, reason="wall-clock budget exhausted")

        # 4) filter the args
        verdict = self._filters.scan(request.args)
        if verdict.blocked:
            return self._finalise(
                request,
                ToolDecision.DENY,
                started,
                reason="secret detected in args",
                findings=[f.__dict__ for f in verdict.findings],
            )

        # 5) execute
        try:
            value = invoke()
        except Exception as exc:
            duration = (time.monotonic() - started) * 1000
            self._audit.record(
                "tool_governor",
                "tool_error",
                request.tool_name,
                "failure",
                rationale=str(exc),
                principal=request.principal,
                duration_ms=duration,
            )
            return ToolResult(
                decision=ToolDecision.ALLOW,
                tool_name=request.tool_name,
                error=str(exc),
                duration_ms=duration,
                reason="invocation raised",
            )

        self._call_count += 1
        self._per_tool[request.tool_name] = self._per_tool.get(request.tool_name, 0) + 1
        return self._finalise(
            request,
            ToolDecision.ALLOW,
            started,
            value=value,
            findings=[f.__dict__ for f in verdict.findings],
        )

    # ---- helpers -----------------------------------------------------

    def _finalise(
        self,
        request: ToolRequest,
        decision: ToolDecision,
        started: float,
        *,
        value: Any = None,
        reason: str = "",
        findings: list[dict] | None = None,
    ) -> ToolResult:
        duration = (time.monotonic() - started) * 1000
        outcome = "success" if decision == ToolDecision.ALLOW else decision.value
        self._audit.record(
            "tool_governor",
            f"governed_call:{request.tool_name}",
            request.tool_name,
            outcome,
            rationale=reason or request.rationale,
            category=request.category.value,
            duration_ms=duration,
            principal=request.principal,
            findings=findings or [],
        )
        return ToolResult(
            decision=decision,
            tool_name=request.tool_name,
            value=value,
            duration_ms=duration,
            reason=reason,
            filter_findings=findings or [],
        )
