"""Cloud Asset Inventory client.

CAI is the one GCP API that returns a unified inventory of every supported
resource type under a project/folder/org. It's the correct entry point for
discovery — beats stitching together N per-service APIs.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator

from google.api_core.exceptions import InvalidArgument
from google.auth.credentials import Credentials
from google.cloud import asset_v1
from google.cloud.asset_v1.types import ContentType

from .models import DiscoveredResource, DiscoveryReport

log = logging.getLogger(__name__)

# Asset types that only exist at organization scope. Including them in a
# project/folder-scoped CAI call fails the *entire batch* with InvalidArgument,
# not just that one type — so filtering them up front prevents dropping every
# other asset type too.
_ORG_ONLY_ASSET_TYPES: frozenset[str] = frozenset(
    {
        "identity.accesscontextmanager.googleapis.com/AccessPolicy",
        "identity.accesscontextmanager.googleapis.com/AccessLevel",
        "identity.accesscontextmanager.googleapis.com/ServicePerimeter",
        "accesscontextmanager.googleapis.com/AccessPolicy",
        "accesscontextmanager.googleapis.com/AccessLevel",
        "accesscontextmanager.googleapis.com/ServicePerimeter",
        "cloudresourcemanager.googleapis.com/Organization",
    }
)


def _filter_by_scope(asset_types: list[str], scope: str) -> tuple[list[str], list[str]]:
    """Return ``(compatible, dropped)`` asset types for the given CAI scope.

    Organization scope keeps everything. Project and folder scopes drop types
    that CAI only supports at org level.
    """
    if scope.startswith("organizations/"):
        return asset_types, []
    compatible = [t for t in asset_types if t not in _ORG_ONLY_ASSET_TYPES]
    dropped = [t for t in asset_types if t in _ORG_ONLY_ASSET_TYPES]
    return compatible, dropped


def _coerce_numbers(obj):
    """Recursively restore integers that round-tripped through proto Struct.

    ``google.protobuf.Value`` only stores numbers as double, so GCP integer
    fields (e.g. ``priority``, ``mtu``, ``port``) come back as 65534.0 after
    ``MessageToDict``/``to_dict``. Terraform rejects a float where the
    provider schema expects an int, so coerce floats with no fractional
    part back to int.
    """
    if isinstance(obj, dict):
        return {k: _coerce_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_numbers(v) for v in obj]
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    return obj


# asset_type_prefix -> (domain, provider)
_DOMAIN_PREFIX: dict[str, str] = {
    # Project-level config: maps to google_project + google_project_service
    "cloudresourcemanager.googleapis.com/Project": "project",
    "serviceusage.googleapis.com/Service": "project",
    # IAM / org
    "cloudresourcemanager.googleapis.com": "iam",
    "iam.googleapis.com": "iam",
    "iap.googleapis.com": "iam",
    "essentialcontacts.googleapis.com": "iam",
    "identity.accesscontextmanager.googleapis.com": "iam",
    "accesscontextmanager.googleapis.com": "iam",
    # Networking — more-specific matches first so they beat compute.*
    "compute.googleapis.com/Network": "networking",
    "compute.googleapis.com/Subnetwork": "networking",
    "compute.googleapis.com/Firewall": "networking",
    "compute.googleapis.com/FirewallPolicy": "networking",
    "compute.googleapis.com/Route": "networking",
    "compute.googleapis.com/Router": "networking",
    "compute.googleapis.com/Address": "networking",
    "compute.googleapis.com/GlobalAddress": "networking",
    "compute.googleapis.com/BackendService": "networking",
    "compute.googleapis.com/RegionBackendService": "networking",
    "compute.googleapis.com/BackendBucket": "networking",
    "compute.googleapis.com/ForwardingRule": "networking",
    "compute.googleapis.com/GlobalForwardingRule": "networking",
    "compute.googleapis.com/HealthCheck": "networking",
    "compute.googleapis.com/HttpHealthCheck": "networking",
    "compute.googleapis.com/HttpsHealthCheck": "networking",
    "compute.googleapis.com/NetworkEndpointGroup": "networking",
    "compute.googleapis.com/SecurityPolicy": "networking",
    "compute.googleapis.com/SslCertificate": "networking",
    "compute.googleapis.com/SslPolicy": "networking",
    "compute.googleapis.com/TargetHttpProxy": "networking",
    "compute.googleapis.com/TargetHttpsProxy": "networking",
    "compute.googleapis.com/TargetTcpProxy": "networking",
    "compute.googleapis.com/TargetSslProxy": "networking",
    "compute.googleapis.com/TargetGrpcProxy": "networking",
    "compute.googleapis.com/UrlMap": "networking",
    "compute.googleapis.com/VpnGateway": "networking",
    "compute.googleapis.com/VpnTunnel": "networking",
    "compute.googleapis.com/Interconnect": "networking",
    "compute.googleapis.com/InterconnectAttachment": "networking",
    "dns.googleapis.com": "networking",
    "networkconnectivity.googleapis.com": "networking",
    "networksecurity.googleapis.com": "networking",
    "certificatemanager.googleapis.com": "networking",
    "vpcaccess.googleapis.com": "networking",
    "servicenetworking.googleapis.com": "networking",
    # Compute & workloads
    "compute.googleapis.com/Instance": "compute",
    "compute.googleapis.com/InstanceGroup": "compute",
    "compute.googleapis.com/InstanceGroupManager": "compute",
    "compute.googleapis.com/InstanceTemplate": "compute",
    "compute.googleapis.com/Autoscaler": "compute",
    "compute.googleapis.com/Disk": "compute",
    "compute.googleapis.com/RegionDisk": "compute",
    "compute.googleapis.com/Snapshot": "compute",
    "compute.googleapis.com/Image": "compute",
    "run.googleapis.com": "compute",
    "cloudfunctions.googleapis.com": "compute",
    "container.googleapis.com": "compute",
    "appengine.googleapis.com": "compute",
    "batch.googleapis.com": "compute",
    "workstations.googleapis.com": "compute",
    "gkehub.googleapis.com": "compute",
    # Storage / data
    "storage.googleapis.com": "storage",
    "bigquery.googleapis.com": "storage",
    "bigtableadmin.googleapis.com": "storage",
    "spanner.googleapis.com": "storage",
    "sqladmin.googleapis.com": "storage",
    "alloydb.googleapis.com": "storage",
    "firestore.googleapis.com": "storage",
    "redis.googleapis.com": "storage",
    "memcache.googleapis.com": "storage",
    "memorystore.googleapis.com": "storage",
    "file.googleapis.com": "storage",
    "dataproc.googleapis.com": "storage",
    "composer.googleapis.com": "storage",
    "analyticshub.googleapis.com": "storage",
    "dataplex.googleapis.com": "storage",
    "datastream.googleapis.com": "storage",
    "dataform.googleapis.com": "storage",
    "metastore.googleapis.com": "storage",
    "storagetransfer.googleapis.com": "storage",
    # Security
    "secretmanager.googleapis.com": "security",
    "cloudkms.googleapis.com": "security",
    "privateca.googleapis.com": "security",
    "binaryauthorization.googleapis.com": "security",
    "ids.googleapis.com": "security",
    "backupdr.googleapis.com": "security",
    # DevOps
    "artifactregistry.googleapis.com": "devops",
    "cloudbuild.googleapis.com": "devops",
    "clouddeploy.googleapis.com": "devops",
    "config.googleapis.com": "devops",
    "developerconnect.googleapis.com": "devops",
    "monitoring.googleapis.com": "devops",
    "logging.googleapis.com": "devops",
    # Other known services (default to "other")
    "pubsub.googleapis.com": "other",
    "cloudtasks.googleapis.com": "other",
    "eventarc.googleapis.com": "other",
    "aiplatform.googleapis.com": "other",
    "workflows.googleapis.com": "other",
    "apigateway.googleapis.com": "other",
    "apigee.googleapis.com": "other",
    "healthcare.googleapis.com": "other",
    "firebase.googleapis.com": "other",
    "notebooks.googleapis.com": "other",
    "apikeys.googleapis.com": "other",
    "serviceusage.googleapis.com": "other",
}


def _domain_for(asset_type: str) -> str:
    # Match most-specific prefix first
    for key in sorted(_DOMAIN_PREFIX, key=len, reverse=True):
        if asset_type.startswith(key):
            return _DOMAIN_PREFIX[key]
    return "other"


class CloudAssetClient:
    """Thin wrapper over google-cloud-asset that returns our DiscoveredResource model."""

    def __init__(self, credentials: Credentials):
        self._client = asset_v1.AssetServiceClient(credentials=credentials)

    def inventory(
        self,
        scope: str,
        asset_types: Iterable[str],
        include_iam: bool = True,
    ) -> DiscoveryReport:
        """Return a report of all matching assets in ``scope``.

        ``scope`` format: "projects/<id>", "folders/<id>", or "organizations/<id>".
        """
        report = DiscoveryReport(scope=scope)
        asset_types = list(asset_types)

        compatible, dropped = _filter_by_scope(asset_types, scope)
        if dropped:
            log.info(
                "dropped %d org-only asset types at scope=%s: %s",
                len(dropped),
                scope,
                sorted(dropped),
            )
            report.errors.append(f"scope_filter_dropped: {sorted(dropped)}")

        # 1) Resource content
        for asset in self._iter_assets(scope, compatible, ContentType.RESOURCE, report):
            report.resources.append(self._to_resource(asset, include_iam_policy=False))

        # 2) IAM policy content (attached back onto the resource by full_resource_name)
        if include_iam:
            by_name = {r.full_resource_name: r for r in report.resources}
            for asset in self._iter_assets(scope, compatible, ContentType.IAM_POLICY, report):
                target = by_name.get(f"//{asset.name.lstrip('/')}") or by_name.get(asset.name)
                if target and asset.iam_policy:
                    target.attributes["iam_policy"] = _policy_to_dict(asset.iam_policy)

        log.info(
            "CAI inventory complete scope=%s resources=%d errors=%d",
            scope,
            len(report.resources),
            len(report.errors),
        )
        return report

    def _iter_assets(
        self,
        scope: str,
        asset_types: list[str],
        content_type: ContentType,
        report: DiscoveryReport,
    ) -> Iterator:
        """Yield assets for ``asset_types`` in ``scope``.

        Tries one batch ``list_assets`` call first. On ``InvalidArgument`` —
        which CAI raises for the whole batch when *any* asset type is
        incompatible with the scope — falls back to per-type calls so the
        incompatible type(s) can be isolated without dropping the rest.
        """
        if not asset_types:
            return

        kind = content_type.name.lower()
        try:
            for asset in self._client.list_assets(
                request={
                    "parent": scope,
                    "asset_types": asset_types,
                    "content_type": content_type,
                }
            ):
                yield asset
            return
        except InvalidArgument as exc:
            log.warning(
                "CAI %s batch call failed (%s); retrying per-type to isolate incompatible types",
                kind,
                exc.message if hasattr(exc, "message") else exc,
            )
            report.errors.append(f"{kind}_batch_fallback")
        except Exception as exc:
            log.exception("CAI %s listing failed", kind)
            report.errors.append(f"{kind}_listing: {exc}")
            return

        for at in asset_types:
            try:
                for asset in self._client.list_assets(
                    request={
                        "parent": scope,
                        "asset_types": [at],
                        "content_type": content_type,
                    }
                ):
                    yield asset
            except InvalidArgument:
                log.info("asset_type=%s incompatible with scope=%s; skipped", at, scope)
                report.errors.append(f"{kind}_incompatible:{at}")
            except Exception as exc:
                log.exception("CAI %s listing failed for %s", kind, at)
                report.errors.append(f"{kind}_listing:{at}: {exc}")

    @staticmethod
    def _to_resource(asset, include_iam_policy: bool) -> DiscoveredResource:
        resource = asset.resource
        # proto-plus' ``to_dict`` recursively unwraps nested Struct/ListValue
        # into native Python types. A naive ``dict(resource.data)`` leaves
        # repeated fields (e.g. Firewall.sourceRanges) as RepeatedComposite,
        # which later breaks ``json.dumps`` in the Jinja templates.
        data: dict = {}
        if resource and resource.data:
            resource_dict = type(resource).to_dict(resource)
            data = _coerce_numbers(resource_dict.get("data") or {})
        name = data.get("name") or asset.name.rsplit("/", 1)[-1]
        # ``resource.location`` is the short form ("us-central1"); ``data.region``/``zone``
        # are often full self-link URLs. Prefer the short form, and fall back to the
        # last slash-segment of the URL form.
        raw_loc = (resource.location if resource else None) or data.get("region") or data.get("zone")
        location = raw_loc.rsplit("/", 1)[-1] if raw_loc else None
        project = _extract_project(asset.name)

        attrs: dict = {k: v for k, v in data.items() if k not in {"labels", "fingerprint"}}
        if include_iam_policy and asset.iam_policy:
            attrs["iam_policy"] = _policy_to_dict(asset.iam_policy)

        return DiscoveredResource(
            provider="gcp",
            domain=_domain_for(asset.asset_type),  # type: ignore[arg-type]
            asset_type=asset.asset_type,
            name=name,
            full_resource_name=asset.name,
            project=project,
            location=location,
            parent=resource.parent if resource else None,
            labels=dict(data.get("labels") or {}),
            attributes=attrs,
            ancestors=list(asset.ancestors or []),
        )


def _extract_project(full_name: str) -> str | None:
    # //service/projects/<id>/...
    parts = full_name.split("/")
    if "projects" in parts:
        i = parts.index("projects")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def _policy_to_dict(policy) -> dict:
    return {
        "bindings": [
            {"role": b.role, "members": list(b.members), "condition": _cond(b.condition)} for b in policy.bindings
        ],
        "etag": policy.etag.hex() if policy.etag else None,
        "version": policy.version,
    }


def _cond(c) -> dict | None:
    if not c or not c.expression:
        return None
    return {"expression": c.expression, "title": c.title, "description": c.description}
