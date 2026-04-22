"""HCL writer.

Consumes the Classification output, groups by domain, renders one .tf file per
domain, and produces an import script so existing resources become tf-managed
in-place (no delete/recreate).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from ..discovery.classifiers import Classified
from ..settings import GenerationCfg
from .naming import default_labels, terraform_address

log = logging.getLogger(__name__)

_DOMAIN_TEMPLATE = {
    "project": "project.tf.j2",
    "iam": "iam.tf.j2",
    "networking": "networking.tf.j2",
    "compute": "compute.tf.j2",
}


class TerraformWriter:
    def __init__(self, cfg: GenerationCfg, environment: str):
        self._cfg = cfg
        self._env_name = environment
        self._jinja = Environment(
            loader=FileSystemLoader(Path(__file__).parent / "templates"),
            autoescape=select_autoescape([]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    # ---- public API -------------------------------------------------------

    def write(self, classified: list[Classified], out_dir: str | Path | None = None) -> Path:
        out = Path(out_dir or self._cfg.output_dir)
        self._reset(out)

        # Provider + backend scaffolding
        (out / "provider.tf").write_text(self._render_provider())

        # Attach deterministic address to every classified entry
        addressed: list[Classified] = []
        for c in classified:
            if c.status == "manual":
                continue
            # Classified is frozen; create a shim attribute via __dict__ sidecar
            c.__dict__["address"] = terraform_address(c.resource)
            addressed.append(c)

        labels = default_labels(self._cfg.labels, self._env_name)

        for domain, template_name in _DOMAIN_TEMPLATE.items():
            subset = [c for c in addressed if c.resource.domain == domain]
            if not subset:
                continue
            tpl = self._jinja.get_template(template_name)
            rendered = tpl.render(classified=subset, labels=labels)
            (out / f"{domain}.tf").write_text(rendered)

        # Import surfaces — TWO formats emitted:
        # 1. imports.tf -- HCL `import { }` blocks (Terraform 1.5+, recommended).
        #    Runs under `terraform plan`, peer-reviewable, auditable.
        # 2. import.sh  -- legacy CLI fallback for Terraform <1.5 / break-glass.
        importable = [c for c in addressed if c.import_id]
        self._write_import_blocks(out, importable)
        self._write_import_script(out, importable)

        # Resources without a Jinja template land on the generate-config-out
        # workflow. They contribute import blocks only; Terraform 1.5+ will
        # synthesise their resource HCL on `plan -generate-config-out=...`.
        import_only = [c for c in importable if not c.first_class]
        if import_only:
            self._write_generate_config_notes(out, import_only)

        # Manual-handling report: resources outside TF coverage
        manual = [c for c in classified if c.status == "manual"]
        if manual:
            (out / "MANUAL_RESOURCES.md").write_text(_manual_report(manual))

        self._run_terraform_fmt(out)

        log.info(
            "HCL generation complete dir=%s domains=%s imports=%d manual=%d",
            out,
            list(_DOMAIN_TEMPLATE),
            sum(1 for c in addressed if c.import_id),
            len(manual),
        )
        return out

    def _run_terraform_fmt(self, out: Path) -> None:
        """Normalise HCL whitespace via ``terraform fmt``.

        Best-effort: the Jinja templates aggressively strip whitespace (via
        ``trim_blocks`` + ``{%- %}``) which can collapse siblings onto one
        line. Running fmt sidesteps per-template whitespace bugs. Skipped if
        the terraform binary isn't on PATH.
        """
        tf = shutil.which("terraform")
        if not tf:
            log.info("terraform not on PATH; skipping fmt (generated HCL may look cramped)")
            return
        try:
            result = subprocess.run(
                [tf, "fmt", "-recursive", str(out)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                log.warning("terraform fmt exited %d: %s", result.returncode, result.stderr.strip())
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("terraform fmt failed: %s", exc)

    # ---- helpers ----------------------------------------------------------

    def _reset(self, out: Path) -> None:
        if out.exists():
            # Wipe prior generation but keep the directory (CI/ownership friendly)
            for p in out.iterdir():
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
        else:
            out.mkdir(parents=True, exist_ok=True)

    def _render_provider(self) -> str:
        tpl = self._jinja.get_template("provider.tf.j2")
        return tpl.render(
            terraform_version=self._cfg.terraform_version,
            provider_version=self._cfg.provider_version,
            default_region="us-central1",
            environment=self._env_name,
        )

    def _write_import_script(self, out: Path, importable: list[Classified]) -> None:
        """Legacy fallback. Kept for Terraform <1.5 and break-glass scripting."""
        if not importable:
            return
        lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
        for c in importable:
            addr = f"{c.tf_type}.{c.__dict__['address']}"
            lines.append(f'terraform import "{addr}" "{c.import_id}"')
        lines.append("")
        script = out / "import.sh"
        script.write_text("\n".join(lines))
        script.chmod(0o755)

    def _write_generate_config_notes(self, out: Path, import_only: list[Classified]) -> None:
        """Instruct operators how to complete import for non-first-class resources."""
        lines = [
            "# Resources imported via `terraform plan -generate-config-out`",
            "",
            "These imports don't have first-class Jinja templates in tf-out.",
            "After `terraform init`, run:",
            "",
            "```bash",
            "terraform plan -generate-config-out=auto_generated.tf",
            "```",
            "",
            "Terraform 1.5+ will synthesise the full `resource { }` HCL for each import",
            "block in this list, writing it to `auto_generated.tf`. Review + apply.",
            "",
            "| Terraform type | Import ID |",
            "|---|---|",
        ]
        for c in import_only:
            lines.append(f"| `{c.tf_type}` | `{c.import_id}` |")
        lines.append("")
        (out / "GENERATE_CONFIG.md").write_text("\n".join(lines))

    def _write_import_blocks(self, out: Path, importable: list[Classified]) -> None:
        """Emit Terraform 1.5+ declarative `import { }` blocks.

        This is the officially recommended way to import at scale — each block
        becomes a plannable import on the next `terraform plan`, so reviewers
        see proposed state changes before any mutation. Blocks are one-shot;
        after a successful `apply`, they can be deleted in a follow-up commit.
        """
        if not importable:
            return
        lines = [
            "# Generated by tf-out. Terraform 1.5+ declarative imports.",
            "# After a successful `terraform apply`, these blocks may be",
            "# deleted — the state entries they created remain.",
            "",
        ]
        for c in importable:
            addr = f"{c.tf_type}.{c.__dict__['address']}"
            lines.append("import {")
            lines.append(f'  id = "{c.import_id}"')
            lines.append(f"  to = {addr}")
            lines.append("}")
            lines.append("")
        (out / "imports.tf").write_text("\n".join(lines))


def _manual_report(manual: list[Classified]) -> str:
    lines = [
        "# Manual-handling required",
        "",
        "These resources were discovered but have no automatic Terraform mapping today.",
        "Review each and either (a) write HCL by hand, (b) extend REGISTRY in",
        "`src/discovery/classifiers.py`, or (c) accept them as unmanaged.",
        "",
        "| asset_type | name | full_resource_name |",
        "|---|---|---|",
    ]
    for c in manual:
        lines.append(f"| `{c.resource.asset_type}` | `{c.resource.name}` | `{c.resource.full_resource_name}` |")
    return "\n".join(lines) + "\n"
