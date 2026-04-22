"""Naming + labeling standards.

Terraform resource addresses need to be deterministic, stable, and collision-free
across re-runs. We derive them from the provider's ``full_resource_name``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from ..discovery.models import DiscoveredResource

_SANITIZE = re.compile(r"[^a-z0-9_]+")


def terraform_address(resource: DiscoveredResource) -> str:
    """Deterministic TF resource local name.

    Regional/zonal resources (subnetworks, instances, addresses, …) can share
    a ``name`` across locations — e.g. a ``default`` subnetwork exists in every
    region. Including the location keeps TF local names unique without a hash.
    Global resources (VPCs, firewalls, global addresses) keep a cleaner
    ``{domain}_{name}`` form.
    """
    parts = [resource.domain]
    loc = (resource.location or "").lower()
    if loc and loc != "global":
        parts.append(loc)
    parts.append(resource.name)
    raw = "_".join(parts).lower()
    addr = _SANITIZE.sub("_", raw).strip("_")
    # TF local names must start with a letter
    if not addr or not addr[0].isalpha():
        addr = f"r_{addr}"
    return addr[:120]


def naming_for(resource: DiscoveredResource, prefix: str, env: str) -> str:
    """User-facing resource name (goes into the HCL ``name`` attribute)."""
    p = prefix.format(env=env)
    candidate = f"{p}{resource.name}".lower()
    return _SANITIZE.sub("-", candidate).strip("-")[:63]


def default_labels(extra: dict[str, str], env: str) -> dict[str, str]:
    out = {
        "managed_by": "tf-out",
        "environment": env,
        "generated_at": datetime.now(UTC).strftime("%Y%m%d"),
    }
    for k, v in (extra or {}).items():
        # Support the settings.yaml convention where value=="runtime" means replace
        out[k] = out.get(k, v) if v == "runtime" else v
    return out
