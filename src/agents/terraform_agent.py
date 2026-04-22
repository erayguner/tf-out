"""Terraform Generation Agent — writes HCL + import script."""

from __future__ import annotations

import logging
from pathlib import Path

from ..generation import TerraformWriter
from ..settings import Settings

log = logging.getLogger(__name__)


class TerraformAgent:
    name = "terraform_generation"

    def __init__(self, settings: Settings):
        self._s = settings

    def run(self, ctx):
        writer = TerraformWriter(self._s.generation, self._s.project.environment)
        out = writer.write(ctx.classified)
        ctx.output_dir = out

        files = sorted(p.name for p in Path(out).iterdir())
        ctx.audit.record(
            self.name,
            "hcl_written",
            str(out),
            "success",
            rationale=f"files={files}",
            files=files,
        )
        return ctx
