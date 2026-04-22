"""Canonical data model for discovered resources.

One provider-agnostic shape so downstream agents (classification, generation,
graph) never care where a resource came from — GCP today, AWS tomorrow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


Provider = Literal["gcp", "aws", "azure"]
Domain = Literal["project", "iam", "networking", "compute", "storage", "security", "devops", "other"]


class DiscoveredResource(BaseModel):
    """A single cloud resource returned from provider discovery."""

    provider: Provider
    domain: Domain
    asset_type: str  # e.g. compute.googleapis.com/Network
    name: str  # provider-native short name
    full_resource_name: str  # e.g. //compute.googleapis.com/projects/.../networks/foo
    project: str | None = None
    location: str | None = None  # region/zone/global
    parent: str | None = None  # organization/folder/project parent
    labels: dict[str, str] = Field(default_factory=dict)

    # Raw attributes returned by the provider (redacted secrets where applicable)
    attributes: dict[str, Any] = Field(default_factory=dict)

    # Ancestry aids org/folder/project IAM inheritance reasoning
    ancestors: list[str] = Field(default_factory=list)

    # Discovery-time metadata
    discovered_at: datetime = Field(default_factory=_utcnow)

    def stable_id(self) -> str:
        """Deterministic ID used as graph node key and TF resource name."""
        return self.full_resource_name.replace("//", "").replace("/", "_").replace(".", "_")


class DiscoveryReport(BaseModel):
    scope: str
    discovered_at: datetime = Field(default_factory=_utcnow)
    resources: list[DiscoveredResource] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def by_domain(self) -> dict[str, list[DiscoveredResource]]:
        out: dict[str, list[DiscoveredResource]] = {}
        for r in self.resources:
            out.setdefault(r.domain, []).append(r)
        return out
