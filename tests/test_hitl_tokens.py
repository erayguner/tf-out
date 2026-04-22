import pytest

from src.governance.hitl import (
    ApprovalExpired,
    ApprovalForged,
    HumanGate,
    mint_token,
)


def test_valid_token_is_accepted(monkeypatch):
    monkeypatch.setenv("AI_TF_HITL_KEY", "shared-key")
    token = mint_token("run-1", "sandbox_apply", "granted", "eray@example.com", "ticket-42")
    monkeypatch.setenv(HumanGate.ENV_TOKEN, token)

    gate = HumanGate(interactive=False)
    a = gate.request("sandbox_apply", "summary", run_id="run-1")
    assert a.granted
    assert a.channel == "token"
    assert a.approver == "eray@example.com"


def test_action_mismatch_rejected(monkeypatch):
    monkeypatch.setenv("AI_TF_HITL_KEY", "shared-key")
    token = mint_token("run-1", "different_action", "granted", "x", "r")
    monkeypatch.setenv(HumanGate.ENV_TOKEN, token)
    gate = HumanGate(interactive=False)
    with pytest.raises(ApprovalForged):
        gate.request("sandbox_apply", "summary", run_id="run-1")


def test_run_id_mismatch_rejected(monkeypatch):
    monkeypatch.setenv("AI_TF_HITL_KEY", "shared-key")
    token = mint_token("run-1", "sandbox_apply", "granted", "x", "r")
    monkeypatch.setenv(HumanGate.ENV_TOKEN, token)
    gate = HumanGate(interactive=False)
    with pytest.raises(ApprovalForged):
        gate.request("sandbox_apply", "summary", run_id="run-2")


def test_expired_token_rejected(monkeypatch):
    monkeypatch.setenv("AI_TF_HITL_KEY", "shared-key")
    token = mint_token("run-1", "sandbox_apply", "granted", "x", "r", ttl_seconds=-1)
    monkeypatch.setenv(HumanGate.ENV_TOKEN, token)
    gate = HumanGate(interactive=False)
    with pytest.raises(ApprovalExpired):
        gate.request("sandbox_apply", "summary", run_id="run-1")


def test_forged_signature_rejected(monkeypatch):
    monkeypatch.setenv("AI_TF_HITL_KEY", "shared-key")
    token = mint_token("run-1", "sandbox_apply", "granted", "x", "r")
    monkeypatch.setenv("AI_TF_HITL_KEY", "different-key")  # attacker flips key
    monkeypatch.setenv(HumanGate.ENV_TOKEN, token)
    gate = HumanGate(interactive=False)
    with pytest.raises(ApprovalForged):
        gate.request("sandbox_apply", "summary", run_id="run-1")


def test_token_not_reusable(monkeypatch):
    monkeypatch.setenv("AI_TF_HITL_KEY", "shared-key")
    token = mint_token("run-1", "sandbox_apply", "granted", "x", "r")
    monkeypatch.setenv(HumanGate.ENV_TOKEN, token)
    gate = HumanGate(interactive=False)
    gate.request("sandbox_apply", "summary", run_id="run-1")
    with pytest.raises(ApprovalForged):
        gate.request("sandbox_apply", "summary", run_id="run-1")


def test_approver_pool_enforced(monkeypatch):
    monkeypatch.setenv("AI_TF_HITL_KEY", "shared-key")
    token = mint_token("run-1", "sandbox_apply", "granted", "stranger@ext.com", "r")
    monkeypatch.setenv(HumanGate.ENV_TOKEN, token)
    gate = HumanGate(interactive=False, approver_pool=["eray@example.com"])
    with pytest.raises(ApprovalForged):
        gate.request("sandbox_apply", "summary", run_id="run-1")
