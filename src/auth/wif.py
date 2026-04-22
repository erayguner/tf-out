"""Workload Identity Federation credential provider.

Agents NEVER use user ADC in production. They exchange an OIDC/JWT token from
their runtime (GKE, Cloud Run, GitHub OIDC, etc.) for a short-lived Google
access token via STS, then impersonate the scoped service account.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

from google.auth import identity_pool, impersonated_credentials
from google.auth.credentials import Credentials
from google.auth.transport.requests import Request

log = logging.getLogger(__name__)

_DEFAULT_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


class WifConfigError(ValueError):
    """Raised when the WIF config file is missing required fields."""


def _load_external_account(path: Path) -> identity_pool.Credentials:
    if not path.exists():
        raise FileNotFoundError(f"WIF config not found: {path}")
    cfg = json.loads(path.read_text())
    if cfg.get("type") != "external_account":
        raise WifConfigError(f"Expected 'external_account' config, got {cfg.get('type')!r}")
    return identity_pool.Credentials.from_info(cfg, scopes=list(_DEFAULT_SCOPES))


def get_credentials(
    wif_config_path: str | Path,
    impersonated_sa: str | None = None,
    scopes: Iterable[str] = _DEFAULT_SCOPES,
) -> Credentials:
    """Return credentials for the agent runtime.

    If ``impersonated_sa`` is provided, the WIF-exchanged token impersonates
    that service account with the requested scopes. Otherwise the federated
    token itself is returned (useful only when the federated principal has
    direct IAM grants — uncommon).
    """
    base = _load_external_account(Path(wif_config_path))

    if not impersonated_sa:
        log.warning("No impersonated_sa set; using federated principal directly")
        base.refresh(Request())
        return base

    creds = impersonated_credentials.Credentials(
        source_credentials=base,
        target_principal=impersonated_sa,
        target_scopes=list(scopes),
        lifetime=3600,
    )
    creds.refresh(Request())
    log.info("WIF credentials acquired for sa=%s", impersonated_sa)
    return creds
