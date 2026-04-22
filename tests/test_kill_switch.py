from pathlib import Path

from src.governance.kill_switch import KillSwitch


def test_not_halted_by_default(tmp_path: Path):
    ks = KillSwitch(run_id="r1", halt_dir=tmp_path)
    halted, reason = ks.check()
    assert not halted
    assert reason == ""


def test_halt_file_is_observed(tmp_path: Path):
    ks = KillSwitch(run_id="r1", halt_dir=tmp_path)
    ks.halt("operator said so")
    halted, reason = ks.check()
    assert halted
    assert reason == "operator said so"


def test_wildcard_halt_file(tmp_path: Path):
    (tmp_path / "all.halt").write_text('{"reason": "org-wide kill"}')
    ks = KillSwitch(run_id="any-run", halt_dir=tmp_path)
    halted, reason = ks.check()
    assert halted
    assert reason == "org-wide kill"


def test_halt_persists_until_operator_clears(tmp_path: Path):
    ks = KillSwitch(run_id="r1", halt_dir=tmp_path)
    ks.halt("x")
    assert ks.check()[0]
    # Re-check during the same session: still halted (sticky within the process)
    assert ks.check()[0]
    ks.clear()
    # After operator explicitly clears, subsequent checks return un-halted
    halted, _ = ks.check()
    assert not halted


def test_env_halt(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AI_TF_HALT", "r1")
    monkeypatch.setenv("AI_TF_HALT_REASON", "ctrl-c equivalent")
    ks = KillSwitch(run_id="r1", halt_dir=tmp_path)
    halted, reason = ks.check()
    assert halted
    assert reason == "ctrl-c equivalent"
