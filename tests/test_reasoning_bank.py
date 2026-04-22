from typing import Any

from src.memory.agentdb_client import SidecarResponse
from src.memory.reasoning_bank import ReasoningBank, Trajectory


class _FakeClient:
    """Minimal stand-in that records calls and serves canned responses."""

    def __init__(self):
        self.stores: list[dict] = []
        self.searches: list[dict] = []
        self.canned_search: dict[str, Any] = {"patterns": [], "reasoning": ""}
        self.store_ok = True

    def store(self, **kw):
        self.stores.append(kw)
        return SidecarResponse(
            ok=self.store_ok, data={"stored": self.store_ok}, error="" if self.store_ok else "simulated"
        )

    def search(self, **kw):
        self.searches.append(kw)
        return SidecarResponse(ok=True, data=self.canned_search)

    def prune(self, **kw):
        return SidecarResponse(ok=True, data={"pruned": 0})


def _trajectory() -> Trajectory:
    return Trajectory(
        correlation_id="cid-1",
        scope="projects/proj-a",
        environment="dev",
        outcome="success",
        resources_discovered=42,
        counts={"supported": 10, "importable": 30, "manual": 2},
        violations=[{"rule": "deny_public_iam", "severity": "warn"}],
        validation_steps=["init", "validate", "plan", "apply", "destroy"],
        rationale="happy path",
    )


def test_record_passes_namespace_and_correlation():
    client = _FakeClient()
    bank = ReasoningBank(client=client, namespace="proj-a")
    bank.record(_trajectory())
    assert client.stores[0]["namespace"] == "proj-a"
    assert client.stores[0]["correlation_id"] == "cid-1"
    assert client.stores[0]["outcome"] == "success"


def test_record_is_fail_open():
    client = _FakeClient()
    client.store_ok = False
    bank = ReasoningBank(client=client, namespace="proj-a")
    response = bank.record(_trajectory())
    # Doesn't raise; returns the failure response
    assert response.ok is False


def test_search_similar_returns_patterns_list():
    client = _FakeClient()
    client.canned_search = {
        "patterns": [{"confidence": 0.9, "outcome": "success", "correlation_id": "prev-1"}],
    }
    bank = ReasoningBank(client=client, namespace="proj-a")
    results = bank.search_similar("scope=proj-a env=dev", k=3)
    assert len(results) == 1
    assert client.searches[0]["k"] == 3


def test_search_similar_empty_on_failure():
    class _FailClient(_FakeClient):
        def search(self, **kw):
            return SidecarResponse(ok=False, error="down")

    bank = ReasoningBank(client=_FailClient(), namespace="proj-a")
    assert bank.search_similar("q") == []


def test_delete_by_correlation_returns_explicit_error():
    # Placeholder implementation must not silently pretend to delete.
    bank = ReasoningBank(client=_FakeClient(), namespace="proj-a")
    r = bank.delete_by_correlation("cid-x")
    assert not r.ok
    assert "not yet wired" in r.error


def test_trajectory_search_text_includes_key_signals():
    txt = _trajectory().to_search_text()
    assert "scope=projects/proj-a" in txt
    assert "outcome=success" in txt
    assert "resources=42" in txt
