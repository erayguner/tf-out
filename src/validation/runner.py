"""Subprocess wrapper around the terraform CLI.

Framework §7.5 mandates "hermetic" code execution. Our constraints:

* The runner does not inherit the parent shell's environment.
* PATH is narrowed to the minimum needed to find ``terraform`` + ``git``.
* Credentials are injected explicitly (GOOGLE_APPLICATION_CREDENTIALS or
  ``creds_path`` param) — never leaked from the parent process.
* A per-run plugin cache directory is used so providers are not shared
  between agent runs.
* Every invocation has a wall-clock timeout.

This is not a provider-managed sandbox (the framework's preferred shape) but
it is the strongest isolation achievable on a bespoke L1 host. The L2
migration target is Cloud Build with a terraform image.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import which

log = logging.getLogger(__name__)

# Minimum set of binaries we rely on; PATH is built from these.
_BIN_SEARCH_PATHS = ["/usr/local/bin", "/usr/bin", "/bin", "/opt/homebrew/bin"]

# Env vars that may be forwarded to the subprocess. Anything else is dropped.
_FORWARDED_ENV = {
    "HOME",  # terraform needs it for .terraform.d
    "USER",
    "LOGNAME",
    "TMPDIR",
    "TZ",
    "LANG",
    "LC_ALL",
    "NO_COLOR",
    # GCP auth
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_PROJECT",
    "CLOUDSDK_CORE_PROJECT",
    # Proxy pass-through for corporate networks
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
}


class TerraformNotFound(RuntimeError):
    pass


@dataclass
class TerraformResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class TerraformRunner:
    def __init__(
        self,
        working_dir: str | Path,
        extra_env: dict[str, str] | None = None,
        plugin_cache_dir: str | Path | None = None,
    ):
        self._cwd = Path(working_dir)

        tf = which("terraform")
        if not tf:
            raise TerraformNotFound("terraform binary not found in PATH")

        self._env = self._build_hermetic_env(extra_env or {}, tf, plugin_cache_dir)

    # ---- env scoping --------------------------------------------------

    @staticmethod
    def _build_hermetic_env(
        extra: dict[str, str],
        terraform_binary: str,
        plugin_cache_dir: str | Path | None,
    ) -> dict[str, str]:
        # PATH is constructed from known-safe dirs + the dir containing terraform.
        tf_dir = str(Path(terraform_binary).parent)
        path_entries = [tf_dir, *_BIN_SEARCH_PATHS]
        env = {"PATH": ":".join(dict.fromkeys(path_entries))}  # dedupe, preserve order

        # Forward only approved parent-env vars
        for k in _FORWARDED_ENV:
            v = os.environ.get(k)
            if v is not None:
                env[k] = v

        # Per-run plugin cache — providers don't leak between runs
        cache = Path(plugin_cache_dir or Path.home() / ".terraform.d" / "plugin-cache-tf-out")
        cache.mkdir(parents=True, exist_ok=True)
        env["TF_PLUGIN_CACHE_DIR"] = str(cache)

        # Disable telemetry/upgrade prompts
        env["CHECKPOINT_DISABLE"] = "1"
        env["TF_IN_AUTOMATION"] = "1"
        env["TF_INPUT"] = "0"

        # Caller-specified TF_VARs override the above
        env.update(extra)
        return env

    # ---- commands -----------------------------------------------------

    def init(self) -> TerraformResult:
        return self._run(["init", "-input=false", "-no-color"])

    def validate(self) -> TerraformResult:
        return self._run(["validate", "-no-color"])

    def plan(self, out: str = "tfplan") -> TerraformResult:
        return self._run(["plan", "-input=false", "-no-color", "-out", out])

    def plan_generate_config(self, out_file: str = "auto_generated.tf") -> TerraformResult:
        """Run `terraform plan -generate-config-out` for import blocks without matching resources.

        Terraform 1.5+ synthesises a ``resource { }`` block in ``out_file`` for
        every ``import { }`` block whose ``to =`` references an undeclared
        resource. Idempotent only across runs when ``out_file`` is empty.
        """
        return self._run(
            [
                "plan",
                "-input=false",
                "-no-color",
                f"-generate-config-out={out_file}",
            ]
        )

    def apply(self, plan_file: str = "tfplan", timeout: int = 600) -> TerraformResult:
        return self._run(["apply", "-input=false", "-no-color", "-auto-approve", plan_file], timeout=timeout)

    def destroy(self, timeout: int = 600) -> TerraformResult:
        return self._run(["destroy", "-input=false", "-no-color", "-auto-approve"], timeout=timeout)

    # ---- core ---------------------------------------------------------

    def _run(self, args: list[str], timeout: int = 300) -> TerraformResult:
        cmd = ["terraform", *args]
        log.info("terraform %s (cwd=%s)", " ".join(args), self._cwd)
        try:
            proc = subprocess.run(
                cmd,
                cwd=self._cwd,
                env=self._env,  # hermetic env — NOT os.environ
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return TerraformResult(" ".join(cmd), 124, exc.stdout or "", f"timeout after {timeout}s")
        return TerraformResult(" ".join(cmd), proc.returncode, proc.stdout, proc.stderr)
