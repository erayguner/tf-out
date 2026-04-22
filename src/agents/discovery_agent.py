"""Discovery Agent — wraps CAI scanning behind a uniform agent interface."""

from __future__ import annotations

import logging
from itertools import chain

from ..auth import resolve as resolve_credentials
from ..discovery import CloudAssetClient
from ..settings import Settings

log = logging.getLogger(__name__)


class DiscoveryAgent:
    name = "discovery"

    def __init__(self, settings: Settings):
        self._s = settings

    def run(self, ctx):
        resolution = resolve_credentials(
            wif_config_path=self._s.auth.wif_config_path or None,
            impersonated_sa=self._s.auth.impersonated_sa or None,
            allow_adc=self._s.auth.allow_adc,
        )
        ctx.audit.record(
            self.name,
            "credentials_resolved",
            resolution.principal,
            "success",
            rationale=resolution.rationale,
            source=resolution.source,
        )

        client = CloudAssetClient(resolution.credentials)
        scope = self._scope()
        asset_types = list(chain.from_iterable(self._s.discovery.asset_types.values()))

        ctx.audit.record(self.name, "scan_started", scope, "success", rationale=f"{len(asset_types)} asset types")

        report = client.inventory(scope, asset_types, include_iam=self._s.discovery.include_iam_policies)
        ctx.discovery = report

        ctx.audit.record(
            self.name,
            "scan_completed",
            scope,
            "failure" if report.errors else "success",
            rationale=f"resources={len(report.resources)} errors={len(report.errors)}",
            resources=len(report.resources),
            errors=report.errors,
        )
        return ctx

    def _scope(self) -> str:
        # CAI scope uses a specific parent form
        p = self._s.project
        if p.scope_type == "project":
            return f"projects/{p.scope_id.removeprefix('projects/')}"
        if p.scope_type == "folder":
            return f"folders/{p.scope_id.removeprefix('folders/')}"
        return f"organizations/{p.scope_id.removeprefix('organizations/')}"
