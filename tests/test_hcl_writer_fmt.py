"""Tests for the ``terraform fmt`` post-step in ``hcl_writer.py``.

The Jinja templates aggressively strip whitespace, which used to collapse
sibling HCL attributes onto one line. ``terraform fmt`` is run at the end of
``TerraformWriter.write`` to sidestep per-template whitespace bugs.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from src.generation.hcl_writer import TerraformWriter
from src.settings import GenerationCfg, NamingCfg


def _writer(tmp_path: Path) -> TerraformWriter:
    cfg = GenerationCfg(
        output_dir=str(tmp_path),
        provider_version="~> 7.0",
        terraform_version=">= 1.14.0",
        naming=NamingCfg(),
        labels={"managed_by": "tf-out"},
    )
    return TerraformWriter(cfg, environment="dev")


def test_run_terraform_fmt_skips_gracefully_when_binary_missing(tmp_path, caplog):
    """If terraform isn't on PATH, we log-and-continue — no exception."""
    import logging

    writer = _writer(tmp_path)
    (tmp_path / "provider.tf").write_text("# dummy")

    with caplog.at_level(logging.INFO, logger="src.generation.hcl_writer"):
        with patch("src.generation.hcl_writer.shutil.which", return_value=None):
            writer._run_terraform_fmt(tmp_path)  # must not raise

    assert "terraform not on PATH" in caplog.text


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform binary not installed")
def test_run_terraform_fmt_normalises_valid_hcl_alignment(tmp_path):
    """End-to-end: fmt re-aligns equals-signs and trims trailing whitespace."""
    unaligned = (
        'resource "google_compute_firewall" "x" {\n'
        '  name = "x"\n'
        "  priority = 65534\n"
        '  source_ranges = ["0.0.0.0/0"]\n'
        "}\n"
    )
    (tmp_path / "x.tf").write_text(unaligned)

    writer = _writer(tmp_path)
    writer._run_terraform_fmt(tmp_path)

    formatted = (tmp_path / "x.tf").read_text()
    # terraform fmt aligns `=` within a block
    lines = [l for l in formatted.splitlines() if "=" in l]
    equals_cols = {l.index("=") for l in lines}
    assert len(equals_cols) == 1, f"equals not aligned: {equals_cols}"
