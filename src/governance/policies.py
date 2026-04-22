"""Policy engine — pre-generation guardrails.

Runs before HCL is written. Pure-function checks so violations are deterministic
and explainable. Adding a rule = adding one function to ``_RULES``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..discovery.classifiers import Classified
from ..settings import GovernanceCfg


@dataclass
class PolicyViolation:
    rule: str
    resource: str
    detail: str
    severity: str  # "deny" blocks run; "warn" is logged only


Rule = Callable[[list[Classified], GovernanceCfg], list[PolicyViolation]]


def _deny_public_iam(classified: list[Classified], cfg: GovernanceCfg) -> list[PolicyViolation]:
    out: list[PolicyViolation] = []
    patterns = set(cfg.deny_patterns)
    for c in classified:
        pol = c.resource.attributes.get("iam_policy") or {}
        for b in pol.get("bindings", []):
            for m in b.get("members", []):
                if any(p in m for p in patterns):
                    out.append(
                        PolicyViolation(
                            rule="deny_public_iam",
                            resource=c.resource.full_resource_name,
                            detail=f"{b['role']} granted to {m}",
                            severity="deny",
                        )
                    )
    return out


def _max_resources(classified: list[Classified], cfg: GovernanceCfg) -> list[PolicyViolation]:
    if len(classified) <= cfg.max_resources_per_run:
        return []
    return [
        PolicyViolation(
            rule="max_resources_per_run",
            resource="<run>",
            detail=f"{len(classified)} > {cfg.max_resources_per_run}",
            severity="deny",
        )
    ]


def _flag_manual_resources(classified: list[Classified], cfg: GovernanceCfg) -> list[PolicyViolation]:
    # Not a block — governance wants visibility that TF won't manage these.
    # The classifier attaches a specific reason when it can (e.g. "route next-hop
    # not supported"); fall back to a generic message for plain unknown types.
    return [
        PolicyViolation(
            rule="manual_resource",
            resource=c.resource.full_resource_name,
            detail=c.reason or f"asset_type {c.resource.asset_type} has no TF mapping",
            severity="warn",
        )
        for c in classified
        if c.status == "manual"
    ]


_RULES: list[Rule] = [_deny_public_iam, _max_resources, _flag_manual_resources]


class PolicyEngine:
    def __init__(self, cfg: GovernanceCfg):
        self._cfg = cfg

    def evaluate(self, classified: list[Classified]) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []
        for rule in _RULES:
            violations.extend(rule(classified, self._cfg))
        return violations

    @staticmethod
    def blocking(violations: list[PolicyViolation]) -> list[PolicyViolation]:
        return [v for v in violations if v.severity == "deny"]
