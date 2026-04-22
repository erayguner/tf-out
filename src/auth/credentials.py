"""Credential provider.

Two supported sources, in priority order:

1. **WIF** (preferred) — external_account config → STS token → SA impersonation.
   This is the posture the framework prescribes (§7.1) and the default in
   production.

2. **ADC** (permitted fallback) — ``google.auth.default()``. Picked up from
   ``gcloud auth application-default login``, GCE metadata, Cloud Run identity,
   etc. Broader blast radius than WIF because it can resolve to a developer's
   user credential. Allowed only when ``auth.allow_adc`` is true in settings.

The chosen source is **always** recorded in the audit log via the caller.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import google.auth
from google.auth.credentials import Credentials
from google.auth.transport.requests import Request

from .wif import get_credentials as _wif_credentials

log = logging.getLogger(__name__)

Source = Literal["wif", "adc"]

_DEFAULT_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


@dataclass(frozen=True)
class CredentialResolution:
    credentials: Credentials
    source: Source
    principal: str  # email / subject shown in Cloud audit logs
    rationale: str  # why this source was chosen


class CredentialError(RuntimeError):
    """Raised when no acceptable credential source is configured."""


def resolve(
    wif_config_path: str | Path | None,
    impersonated_sa: str | None,
    allow_adc: bool,
    scopes: Iterable[str] = _DEFAULT_SCOPES,
) -> CredentialResolution:
    """Pick WIF if configured, else ADC if permitted, else raise."""
    # 1) WIF preferred
    if wif_config_path and Path(wif_config_path).exists():
        creds = _wif_credentials(wif_config_path, impersonated_sa, scopes)
        principal = impersonated_sa or getattr(creds, "service_account_email", "wif-federated")
        return CredentialResolution(
            credentials=creds,
            source="wif",
            principal=principal,
            rationale="WIF config present; preferred per §7.1",
        )

    # 2) ADC fallback — only if explicitly enabled
    if not allow_adc:
        raise CredentialError(
            "No WIF config found and auth.allow_adc=false. "
            "Either set wif_config_path or opt in to ADC (allow_adc: true)."
        )

    creds, project = google.auth.default(scopes=list(scopes))
    creds.refresh(Request())
    principal = getattr(creds, "service_account_email", None) or getattr(creds, "signer_email", None) or "adc-unknown"
    log.warning(
        "Using ADC credentials (principal=%s, project=%s). Broader blast radius than WIF.",
        principal,
        project,
    )
    return CredentialResolution(
        credentials=creds,
        source="adc",
        principal=str(principal),
        rationale="WIF not configured; ADC permitted by auth.allow_adc=true",
    )
