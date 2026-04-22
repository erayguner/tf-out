import json
from pathlib import Path

from src.discovery.classifiers import classify_all
from src.discovery.models import DiscoveredResource
from src.governance import AuditLog, PolicyEngine
from src.settings import GovernanceCfg


def _gov_cfg(**kw) -> GovernanceCfg:
    return GovernanceCfg(
        audit_log_dir=kw.pop("audit_log_dir", "audit-logs"),
        hitl_required_for=[],
        max_resources_per_run=kw.pop("max_resources_per_run", 500),
        deny_patterns=kw.pop("deny_patterns", ["allUsers", "allAuthenticatedUsers"]),
    )


def test_audit_log_is_append_only(tmp_path: Path):
    log = AuditLog(tmp_path)
    log.record("unit", "did_a_thing", "target1", "success")
    log.record("unit", "did_another", "target2", "failure", rationale="boom")

    lines = log.path.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["actor"] == "unit" and first["action"] == "did_a_thing"


def test_deny_public_iam_binding_triggers_violation(sample_network):
    sample_network.attributes["iam_policy"] = {
        "bindings": [{"role": "roles/storage.objectViewer", "members": ["allUsers"], "condition": None}],
        "etag": None,
        "version": 1,
    }
    engine = PolicyEngine(_gov_cfg())
    violations = engine.evaluate(classify_all([sample_network]))
    blocking = engine.blocking(violations)
    assert any(v.rule == "deny_public_iam" for v in blocking)


def test_manual_resources_produce_warnings_not_denies():
    r = DiscoveredResource(
        provider="gcp",
        domain="other",
        asset_type="exotic.googleapis.com/Thing",
        name="x",
        full_resource_name="//exotic/x",
    )
    engine = PolicyEngine(_gov_cfg())
    violations = engine.evaluate(classify_all([r]))
    assert violations and all(v.severity == "warn" for v in violations)
    assert engine.blocking(violations) == []


def test_max_resources_per_run(sample_report):
    engine = PolicyEngine(_gov_cfg(max_resources_per_run=1))
    violations = engine.evaluate(classify_all(sample_report.resources))
    assert any(v.rule == "max_resources_per_run" for v in engine.blocking(violations))
