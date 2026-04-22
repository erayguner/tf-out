import json
from pathlib import Path

import pytest

from src.governance.audit import AuditLog, ChainBroken


def test_chain_links_each_entry_to_the_previous(tmp_path: Path):
    log = AuditLog(tmp_path)
    a = log.record("unit", "a", "t", "success")
    b = log.record("unit", "b", "t", "success")
    assert b.prev_hash == a.hash
    assert log.head_hash == b.hash


def test_verify_chain_returns_entry_count(tmp_path: Path):
    log = AuditLog(tmp_path)
    for i in range(5):
        log.record("unit", f"step{i}", "t", "success")
    assert log.verify_chain() == 5


def test_tamper_is_detected(tmp_path: Path):
    log = AuditLog(tmp_path)
    log.record("unit", "a", "t", "success")
    log.record("unit", "b", "t", "success")

    # Forge an entry — rewrite the first line's rationale
    lines = log.path.read_text().splitlines()
    forged = json.loads(lines[0])
    forged["rationale"] = "tampered"
    lines[0] = json.dumps(forged, separators=(",", ":"), sort_keys=True)
    log.path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ChainBroken):
        log.verify_chain()


def test_manifest_is_signed(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AI_TF_AUDIT_HMAC_KEY", "test-key")
    log = AuditLog(tmp_path)
    log.record("unit", "a", "t", "success")
    manifest = log.write_manifest()
    assert manifest["entry_count"] == 1
    assert manifest["signature_algorithm"] == "hmac-sha256"
    assert len(manifest["signature"]) == 64  # hex SHA-256


def test_signed_export_roundtrips(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AI_TF_AUDIT_HMAC_KEY", "test-key")
    log = AuditLog(tmp_path)
    log.record("unit", "a", "t", "success")
    log.record("unit", "b", "t", "success")

    bundle = log.export_signed()
    assert bundle["payload"]["entry_count"] == 2
    assert bundle["algorithm"] == "hmac-sha256"
    assert isinstance(bundle["signature"], str)
