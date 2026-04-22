"""GCP asset_type -> Terraform resource kind mapping.

Coverage: built from Google's canonical Cloud Asset Inventory list
(https://cloud.google.com/asset-inventory/docs/asset-types) cross-referenced
with the hashicorp/google provider 7.x import documentation.

Buckets:
  * ``supported`` / ``importable`` — we can emit an ``import { }`` block with a
    canonical, provider-documented import ID.
  * ``manual`` — no known TF mapping; flagged in MANUAL_RESOURCES.md.

Within the ``importable`` set, we distinguish two *tiers*:

  * ``first_class = True``  — we ship a Jinja domain template that emits the
    full resource HCL. The resulting module applies straight from ``apply``.
  * ``first_class = False`` — we emit the import block only. Operators run
    ``terraform plan -generate-config-out=auto_generated.tf`` (Terraform 1.5+)
    to let Terraform synthesise the resource HCL from live state.

This two-tier design lets us cover ~80 resource types at import time without
writing 80 templates.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import DiscoveredResource


@dataclass(frozen=True)
class Mapping:
    tf_type: str
    importable: bool
    import_id: Callable[[DiscoveredResource], str] | None = None
    first_class: bool = False  # True when a domain template exists


# --- path-shape builders ----------------------------------------------------
#
# Google provider import IDs follow a small number of path shapes. Every one
# below is the *canonical* (fully-qualified) form documented in the registry.
# Shorthand forms are also accepted but canonical survives upgrades best.


def _global(kind: str):
    """projects/{p}/global/{kind}/{name}"""
    return lambda r: f"projects/{r.project}/global/{kind}/{r.name}"


def _regional(kind: str):
    """projects/{p}/regions/{region}/{kind}/{name}"""
    return lambda r: f"projects/{r.project}/regions/{r.location}/{kind}/{r.name}"


def _zonal(kind: str):
    """projects/{p}/zones/{zone}/{kind}/{name}"""
    return lambda r: f"projects/{r.project}/zones/{r.location}/{kind}/{r.name}"


def _loc(kind: str):
    """projects/{p}/locations/{loc}/{kind}/{name} (most modern APIs)"""
    return lambda r: f"projects/{r.project}/locations/{r.location}/{kind}/{r.name}"


def _proj(kind: str):
    """projects/{p}/{kind}/{name} (flat project-scoped resources)"""
    return lambda r: f"projects/{r.project}/{kind}/{r.name}"


REGISTRY: dict[str, Mapping] = {
    # --- IAM / organization ------------------------------------------------
    "iam.googleapis.com/ServiceAccount": Mapping(
        "google_service_account",
        True,
        first_class=True,
        import_id=lambda r: f"projects/{r.project}/serviceAccounts/{r.attributes.get('email', r.name)}",
    ),
    "iam.googleapis.com/Role": Mapping(
        "google_project_iam_custom_role",
        True,
        first_class=True,
        import_id=lambda r: f"projects/{r.project}/roles/{r.name}",
    ),
    "iam.googleapis.com/WorkloadIdentityPool": Mapping(
        "google_iam_workload_identity_pool",
        True,
        import_id=lambda r: f"projects/{r.project}/locations/global/workloadIdentityPools/{r.name}",
    ),
    "iam.googleapis.com/WorkloadIdentityPoolProvider": Mapping(
        "google_iam_workload_identity_pool_provider",
        True,
        # Parent is stored in .attributes; fall back to name-derived path
        import_id=lambda r: r.attributes.get("name") or r.full_resource_name.lstrip("/"),
    ),
    "iam.googleapis.com/WorkforcePool": Mapping(
        "google_iam_workforce_pool",
        True,
        import_id=lambda r: f"locations/global/workforcePools/{r.name}",
    ),
    "iap.googleapis.com/TunnelDestGroup": Mapping(
        "google_iap_tunnel_dest_group",
        True,
        import_id=lambda r: f"projects/{r.project}/iap_tunnel/locations/{r.location}/destGroups/{r.name}",
    ),
    "cloudresourcemanager.googleapis.com/Project": Mapping(
        "google_project",
        True,
        first_class=True,
        import_id=lambda r: r.name,
    ),
    "cloudresourcemanager.googleapis.com/Folder": Mapping(
        "google_folder",
        True,
        import_id=lambda r: f"folders/{r.name}",
    ),
    "essentialcontacts.googleapis.com/Contact": Mapping(
        "google_essential_contacts_contact",
        True,
        import_id=lambda r: r.full_resource_name.lstrip("/"),
    ),
    "identity.accesscontextmanager.googleapis.com/AccessLevel": Mapping(
        "google_access_context_manager_access_level",
        True,
        import_id=lambda r: r.full_resource_name.lstrip("/"),
    ),
    "identity.accesscontextmanager.googleapis.com/AccessPolicy": Mapping(
        "google_access_context_manager_access_policy",
        True,
        import_id=lambda r: r.name,
    ),
    "identity.accesscontextmanager.googleapis.com/ServicePerimeter": Mapping(
        "google_access_context_manager_service_perimeter",
        True,
        import_id=lambda r: r.full_resource_name.lstrip("/"),
    ),
    # --- Networking / VPC --------------------------------------------------
    "compute.googleapis.com/Network": Mapping("google_compute_network", True, _global("networks"), first_class=True),
    "compute.googleapis.com/Subnetwork": Mapping(
        "google_compute_subnetwork", True, _regional("subnetworks"), first_class=True
    ),
    "compute.googleapis.com/Firewall": Mapping("google_compute_firewall", True, _global("firewalls"), first_class=True),
    "compute.googleapis.com/Route": Mapping("google_compute_route", True, _global("routes"), first_class=True),
    "compute.googleapis.com/Router": Mapping("google_compute_router", True, _regional("routers"), first_class=True),
    "compute.googleapis.com/FirewallPolicy": Mapping(
        "google_compute_firewall_policy", True, import_id=lambda r: f"locations/global/firewallPolicies/{r.name}"
    ),
    "compute.googleapis.com/Address": Mapping("google_compute_address", True, _regional("addresses")),
    "compute.googleapis.com/GlobalAddress": Mapping("google_compute_global_address", True, _global("addresses")),
    "compute.googleapis.com/BackendService": Mapping(
        "google_compute_backend_service", True, _global("backendServices")
    ),
    "compute.googleapis.com/RegionBackendService": Mapping(
        "google_compute_region_backend_service", True, _regional("backendServices")
    ),
    "compute.googleapis.com/BackendBucket": Mapping("google_compute_backend_bucket", True, _global("backendBuckets")),
    "compute.googleapis.com/ForwardingRule": Mapping(
        "google_compute_forwarding_rule", True, _regional("forwardingRules")
    ),
    "compute.googleapis.com/GlobalForwardingRule": Mapping(
        "google_compute_global_forwarding_rule", True, _global("forwardingRules")
    ),
    "compute.googleapis.com/HealthCheck": Mapping("google_compute_health_check", True, _global("healthChecks")),
    "compute.googleapis.com/HttpHealthCheck": Mapping(
        "google_compute_http_health_check", True, _global("httpHealthChecks")
    ),
    "compute.googleapis.com/HttpsHealthCheck": Mapping(
        "google_compute_https_health_check", True, _global("httpsHealthChecks")
    ),
    "compute.googleapis.com/NetworkEndpointGroup": Mapping(
        "google_compute_network_endpoint_group", True, _zonal("networkEndpointGroups")
    ),
    "compute.googleapis.com/NetworkAttachment": Mapping(
        "google_compute_network_attachment", True, _regional("networkAttachments")
    ),
    "compute.googleapis.com/PacketMirroring": Mapping(
        "google_compute_packet_mirroring", True, _regional("packetMirrorings")
    ),
    "compute.googleapis.com/SecurityPolicy": Mapping(
        "google_compute_security_policy", True, _global("securityPolicies")
    ),
    "compute.googleapis.com/ServiceAttachment": Mapping(
        "google_compute_service_attachment", True, _regional("serviceAttachments")
    ),
    "compute.googleapis.com/SslCertificate": Mapping(
        "google_compute_ssl_certificate", True, _global("sslCertificates")
    ),
    "compute.googleapis.com/SslPolicy": Mapping("google_compute_ssl_policy", True, _global("sslPolicies")),
    "compute.googleapis.com/TargetHttpProxy": Mapping(
        "google_compute_target_http_proxy", True, _global("targetHttpProxies")
    ),
    "compute.googleapis.com/TargetHttpsProxy": Mapping(
        "google_compute_target_https_proxy", True, _global("targetHttpsProxies")
    ),
    "compute.googleapis.com/TargetTcpProxy": Mapping(
        "google_compute_target_tcp_proxy", True, _global("targetTcpProxies")
    ),
    "compute.googleapis.com/TargetSslProxy": Mapping(
        "google_compute_target_ssl_proxy", True, _global("targetSslProxies")
    ),
    "compute.googleapis.com/TargetGrpcProxy": Mapping(
        "google_compute_target_grpc_proxy", True, _global("targetGrpcProxies")
    ),
    "compute.googleapis.com/TargetInstance": Mapping("google_compute_target_instance", True, _zonal("targetInstances")),
    "compute.googleapis.com/TargetPool": Mapping("google_compute_target_pool", True, _regional("targetPools")),
    "compute.googleapis.com/UrlMap": Mapping("google_compute_url_map", True, _global("urlMaps")),
    "compute.googleapis.com/VpnGateway": Mapping("google_compute_ha_vpn_gateway", True, _regional("vpnGateways")),
    "compute.googleapis.com/TargetVpnGateway": Mapping(
        "google_compute_vpn_gateway", True, _regional("targetVpnGateways")
    ),
    "compute.googleapis.com/ExternalVpnGateway": Mapping(
        "google_compute_external_vpn_gateway", True, _global("externalVpnGateways")
    ),
    "compute.googleapis.com/VpnTunnel": Mapping("google_compute_vpn_tunnel", True, _regional("vpnTunnels")),
    "compute.googleapis.com/Interconnect": Mapping("google_compute_interconnect", True, _global("interconnects")),
    "compute.googleapis.com/InterconnectAttachment": Mapping(
        "google_compute_interconnect_attachment", True, _regional("interconnectAttachments")
    ),
    "compute.googleapis.com/PublicAdvertisedPrefix": Mapping(
        "google_compute_public_advertised_prefix", True, _global("publicAdvertisedPrefixes")
    ),
    "compute.googleapis.com/PublicDelegatedPrefix": Mapping(
        "google_compute_public_delegated_prefix", True, _regional("publicDelegatedPrefixes")
    ),
    "dns.googleapis.com/ManagedZone": Mapping(
        "google_dns_managed_zone",
        True,
        first_class=True,
        import_id=lambda r: f"projects/{r.project}/managedZones/{r.name}",
    ),
    "dns.googleapis.com/Policy": Mapping(
        "google_dns_policy", True, import_id=lambda r: f"projects/{r.project}/policies/{r.name}"
    ),
    "dns.googleapis.com/ResponsePolicy": Mapping(
        "google_dns_response_policy", True, import_id=lambda r: f"projects/{r.project}/responsePolicies/{r.name}"
    ),
    "networkconnectivity.googleapis.com/Hub": Mapping("google_network_connectivity_hub", True, _loc("global/hubs")),
    "networkconnectivity.googleapis.com/Spoke": Mapping("google_network_connectivity_spoke", True, _loc("spokes")),
    "networkconnectivity.googleapis.com/InternalRange": Mapping(
        "google_network_connectivity_internal_range", True, _loc("global/internalRanges")
    ),
    "networkconnectivity.googleapis.com/PolicyBasedRoute": Mapping(
        "google_network_connectivity_policy_based_route", True, _loc("global/policyBasedRoutes")
    ),
    "certificatemanager.googleapis.com/Certificate": Mapping(
        "google_certificate_manager_certificate", True, _loc("certificates")
    ),
    "certificatemanager.googleapis.com/CertificateMap": Mapping(
        "google_certificate_manager_certificate_map", True, _loc("certificateMaps")
    ),
    "certificatemanager.googleapis.com/CertificateMapEntry": Mapping(
        "google_certificate_manager_certificate_map_entry",
        True,
        import_id=lambda r: (
            f"projects/{r.project}/locations/{r.location}/certificateMaps/{r.attributes.get('parent', '_')}/certificateMapEntries/{r.name}"
        ),
    ),
    "certificatemanager.googleapis.com/DnsAuthorization": Mapping(
        "google_certificate_manager_dns_authorization", True, _loc("dnsAuthorizations")
    ),
    "certificatemanager.googleapis.com/TrustConfig": Mapping(
        "google_certificate_manager_trust_config", True, _loc("trustConfigs")
    ),
    # --- Compute & workloads ----------------------------------------------
    "compute.googleapis.com/Instance": Mapping("google_compute_instance", True, _zonal("instances"), first_class=True),
    "compute.googleapis.com/InstanceGroup": Mapping("google_compute_instance_group", True, _zonal("instanceGroups")),
    "compute.googleapis.com/InstanceGroupManager": Mapping(
        "google_compute_instance_group_manager", True, _zonal("instanceGroupManagers"), first_class=True
    ),
    "compute.googleapis.com/InstanceTemplate": Mapping(
        "google_compute_instance_template", True, _global("instanceTemplates")
    ),
    "compute.googleapis.com/Disk": Mapping("google_compute_disk", True, _zonal("disks")),
    "compute.googleapis.com/RegionDisk": Mapping("google_compute_region_disk", True, _regional("disks")),
    "compute.googleapis.com/Snapshot": Mapping("google_compute_snapshot", True, _global("snapshots")),
    "compute.googleapis.com/Image": Mapping("google_compute_image", True, _global("images")),
    "compute.googleapis.com/Autoscaler": Mapping("google_compute_autoscaler", True, _zonal("autoscalers")),
    "compute.googleapis.com/ResourcePolicy": Mapping(
        "google_compute_resource_policy", True, _regional("resourcePolicies")
    ),
    "compute.googleapis.com/Reservation": Mapping("google_compute_reservation", True, _zonal("reservations")),
    "run.googleapis.com/Service": Mapping(
        "google_cloud_run_v2_service",
        True,
        first_class=True,
        import_id=lambda r: f"projects/{r.project}/locations/{r.location}/services/{r.name}",
    ),
    "run.googleapis.com/Job": Mapping("google_cloud_run_v2_job", True, _loc("jobs")),
    "run.googleapis.com/WorkerPool": Mapping("google_cloud_run_v2_worker_pool", True, _loc("workerPools")),
    "run.googleapis.com/DomainMapping": Mapping("google_cloud_run_domain_mapping", True, _loc("domainmappings")),
    "cloudfunctions.googleapis.com/Function": Mapping("google_cloudfunctions2_function", True, _loc("functions")),
    "cloudfunctions.googleapis.com/CloudFunction": Mapping("google_cloudfunctions_function", True, _loc("functions")),
    "container.googleapis.com/Cluster": Mapping("google_container_cluster", True, _loc("clusters")),
    "container.googleapis.com/NodePool": Mapping(
        "google_container_node_pool",
        True,
        import_id=lambda r: (
            f"projects/{r.project}/locations/{r.location}/clusters/{r.attributes.get('cluster', '_')}/nodePools/{r.name}"
        ),
    ),
    "appengine.googleapis.com/Application": Mapping("google_app_engine_application", True, import_id=lambda r: r.name),
    "appengine.googleapis.com/Service": Mapping(
        "google_app_engine_service_split_traffic", True, import_id=lambda r: f"apps/{r.project}/services/{r.name}"
    ),
    "batch.googleapis.com/Job": Mapping("google_batch_job", True, _loc("jobs")),
    "workstations.googleapis.com/WorkstationCluster": Mapping(
        "google_workstations_workstation_cluster", True, _loc("workstationClusters")
    ),
    "workstations.googleapis.com/WorkstationConfig": Mapping(
        "google_workstations_workstation_config",
        True,
        import_id=lambda r: (
            f"projects/{r.project}/locations/{r.location}/workstationClusters/{r.attributes.get('parent', '_')}/workstationConfigs/{r.name}"
        ),
    ),
    "workstations.googleapis.com/Workstation": Mapping(
        "google_workstations_workstation", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "gkehub.googleapis.com/Membership": Mapping("google_gke_hub_membership", True, _loc("memberships")),
    "gkehub.googleapis.com/Feature": Mapping("google_gke_hub_feature", True, _loc("features")),
    "gkehub.googleapis.com/Fleet": Mapping(
        "google_gke_hub_fleet", True, import_id=lambda r: f"projects/{r.project}/locations/{r.location}/fleets/default"
    ),
    # --- Storage / data ---------------------------------------------------
    "storage.googleapis.com/Bucket": Mapping(
        "google_storage_bucket", True, import_id=lambda r: f"{r.project}/{r.name}"
    ),
    "bigquery.googleapis.com/Dataset": Mapping(
        "google_bigquery_dataset", True, import_id=lambda r: f"projects/{r.project}/datasets/{r.name}"
    ),
    "bigquery.googleapis.com/Table": Mapping(
        "google_bigquery_table",
        True,
        import_id=lambda r: (
            f"projects/{r.project}/datasets/{r.attributes.get('datasetReference', {}).get('datasetId', '_')}/tables/{r.name}"
        ),
    ),
    "bigquery.googleapis.com/Routine": Mapping(
        "google_bigquery_routine", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "sqladmin.googleapis.com/Instance": Mapping(
        "google_sql_database_instance", True, import_id=lambda r: f"projects/{r.project}/instances/{r.name}"
    ),
    "spanner.googleapis.com/Instance": Mapping(
        "google_spanner_instance", True, import_id=lambda r: f"{r.project}/{r.name}"
    ),
    "spanner.googleapis.com/Database": Mapping(
        "google_spanner_database", True, import_id=lambda r: f"{r.project}/{r.attributes.get('parent', '_')}/{r.name}"
    ),
    "bigtableadmin.googleapis.com/Instance": Mapping(
        "google_bigtable_instance", True, import_id=lambda r: f"projects/{r.project}/instances/{r.name}"
    ),
    "bigtableadmin.googleapis.com/Table": Mapping(
        "google_bigtable_table",
        True,
        import_id=lambda r: f"projects/{r.project}/instances/{r.attributes.get('parent', '_')}/tables/{r.name}",
    ),
    "firestore.googleapis.com/Database": Mapping(
        "google_firestore_database", True, import_id=lambda r: f"projects/{r.project}/databases/{r.name}"
    ),
    "redis.googleapis.com/Instance": Mapping("google_redis_instance", True, _loc("instances")),
    "redis.googleapis.com/Cluster": Mapping("google_redis_cluster", True, _loc("clusters")),
    "memcache.googleapis.com/Instance": Mapping("google_memcache_instance", True, _loc("instances")),
    "memorystore.googleapis.com/Instance": Mapping("google_memorystore_instance", True, _loc("instances")),
    "alloydb.googleapis.com/Cluster": Mapping("google_alloydb_cluster", True, _loc("clusters")),
    "alloydb.googleapis.com/Instance": Mapping(
        "google_alloydb_instance",
        True,
        import_id=lambda r: (
            f"projects/{r.project}/locations/{r.location}/clusters/{r.attributes.get('parent', '_')}/instances/{r.name}"
        ),
    ),
    "alloydb.googleapis.com/Backup": Mapping("google_alloydb_backup", True, _loc("backups")),
    "file.googleapis.com/Instance": Mapping("google_filestore_instance", True, _loc("instances")),
    "file.googleapis.com/Backup": Mapping("google_filestore_backup", True, _loc("backups")),
    "dataproc.googleapis.com/Cluster": Mapping(
        "google_dataproc_cluster", True, import_id=lambda r: f"{r.project}/{r.location}/{r.name}"
    ),
    "dataproc.googleapis.com/AutoscalingPolicy": Mapping(
        "google_dataproc_autoscaling_policy",
        True,
        import_id=lambda r: f"projects/{r.project}/locations/{r.location}/autoscalingPolicies/{r.name}",
    ),
    "dataproc.googleapis.com/WorkflowTemplate": Mapping(
        "google_dataproc_workflow_template",
        True,
        import_id=lambda r: f"projects/{r.project}/locations/{r.location}/workflowTemplates/{r.name}",
    ),
    "composer.googleapis.com/Environment": Mapping("google_composer_environment", True, _loc("environments")),
    "analyticshub.googleapis.com/DataExchange": Mapping(
        "google_bigquery_analytics_hub_data_exchange", True, _loc("dataExchanges")
    ),
    "analyticshub.googleapis.com/Listing": Mapping(
        "google_bigquery_analytics_hub_listing", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "dataplex.googleapis.com/Lake": Mapping("google_dataplex_lake", True, _loc("lakes")),
    "dataplex.googleapis.com/Zone": Mapping(
        "google_dataplex_zone", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "dataplex.googleapis.com/Asset": Mapping(
        "google_dataplex_asset", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "datastream.googleapis.com/Stream": Mapping("google_datastream_stream", True, _loc("streams")),
    "datastream.googleapis.com/ConnectionProfile": Mapping(
        "google_datastream_connection_profile", True, _loc("connectionProfiles")
    ),
    "datastream.googleapis.com/PrivateConnection": Mapping(
        "google_datastream_private_connection", True, _loc("privateConnections")
    ),
    # --- Security ---------------------------------------------------------
    "cloudkms.googleapis.com/KeyRing": Mapping("google_kms_key_ring", True, _loc("keyRings")),
    "cloudkms.googleapis.com/CryptoKey": Mapping(
        "google_kms_crypto_key",
        True,
        import_id=lambda r: (
            f"projects/{r.project}/locations/{r.location}/keyRings/{r.attributes.get('parent', '_')}/cryptoKeys/{r.name}"
        ),
    ),
    "cloudkms.googleapis.com/EkmConnection": Mapping("google_kms_ekm_connection", True, _loc("ekmConnections")),
    "secretmanager.googleapis.com/Secret": Mapping(
        "google_secret_manager_secret", True, import_id=lambda r: f"projects/{r.project}/secrets/{r.name}"
    ),
    "secretmanager.googleapis.com/SecretVersion": Mapping(
        "google_secret_manager_secret_version", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "privateca.googleapis.com/CaPool": Mapping("google_privateca_ca_pool", True, _loc("caPools")),
    "privateca.googleapis.com/CertificateAuthority": Mapping(
        "google_privateca_certificate_authority", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "privateca.googleapis.com/Certificate": Mapping(
        "google_privateca_certificate", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "privateca.googleapis.com/CertificateTemplate": Mapping(
        "google_privateca_certificate_template", True, _loc("certificateTemplates")
    ),
    "binaryauthorization.googleapis.com/Policy": Mapping(
        "google_binary_authorization_policy", True, import_id=lambda r: r.project
    ),
    "binaryauthorization.googleapis.com/Attestor": Mapping(
        "google_binary_authorization_attestor", True, import_id=lambda r: f"projects/{r.project}/attestors/{r.name}"
    ),
    "ids.googleapis.com/Endpoint": Mapping("google_cloud_ids_endpoint", True, _loc("endpoints")),
    # --- DevOps / build / deploy -----------------------------------------
    "artifactregistry.googleapis.com/Repository": Mapping(
        "google_artifact_registry_repository", True, _loc("repositories")
    ),
    "cloudbuild.googleapis.com/BuildTrigger": Mapping(
        "google_cloudbuild_trigger", True, import_id=lambda r: f"projects/{r.project}/triggers/{r.name}"
    ),
    "cloudbuild.googleapis.com/Connection": Mapping("google_cloudbuildv2_connection", True, _loc("connections")),
    "cloudbuild.googleapis.com/Repository": Mapping(
        "google_cloudbuildv2_repository", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "cloudbuild.googleapis.com/WorkerPool": Mapping("google_cloudbuild_worker_pool", True, _loc("workerPools")),
    "clouddeploy.googleapis.com/DeliveryPipeline": Mapping(
        "google_clouddeploy_delivery_pipeline", True, _loc("deliveryPipelines")
    ),
    "clouddeploy.googleapis.com/Target": Mapping("google_clouddeploy_target", True, _loc("targets")),
    "clouddeploy.googleapis.com/Automation": Mapping(
        "google_clouddeploy_automation", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "clouddeploy.googleapis.com/CustomTargetType": Mapping(
        "google_clouddeploy_custom_target_type", True, _loc("customTargetTypes")
    ),
    "clouddeploy.googleapis.com/DeployPolicy": Mapping(
        "google_clouddeploy_deploy_policy", True, _loc("deployPolicies")
    ),
    "config.googleapis.com/Deployment": Mapping("google_infra_manager_deployment", True, _loc("deployments")),
    "developerconnect.googleapis.com/Connection": Mapping(
        "google_developer_connect_connection", True, _loc("connections")
    ),
    "developerconnect.googleapis.com/GitRepositoryLink": Mapping(
        "google_developer_connect_git_repository_link", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    # --- Messaging / events ----------------------------------------------
    "pubsub.googleapis.com/Topic": Mapping(
        "google_pubsub_topic", True, import_id=lambda r: f"projects/{r.project}/topics/{r.name}"
    ),
    "pubsub.googleapis.com/Subscription": Mapping(
        "google_pubsub_subscription", True, import_id=lambda r: f"projects/{r.project}/subscriptions/{r.name}"
    ),
    "pubsub.googleapis.com/Schema": Mapping(
        "google_pubsub_schema", True, import_id=lambda r: f"projects/{r.project}/schemas/{r.name}"
    ),
    "cloudtasks.googleapis.com/Queue": Mapping("google_cloud_tasks_queue", True, _loc("queues")),
    "eventarc.googleapis.com/Trigger": Mapping("google_eventarc_trigger", True, _loc("triggers")),
    "eventarc.googleapis.com/Channel": Mapping("google_eventarc_channel", True, _loc("channels")),
    "eventarc.googleapis.com/MessageBus": Mapping("google_eventarc_message_bus", True, _loc("messageBuses")),
    "eventarc.googleapis.com/Pipeline": Mapping("google_eventarc_pipeline", True, _loc("pipelines")),
    "eventarc.googleapis.com/Enrollment": Mapping("google_eventarc_enrollment", True, _loc("enrollments")),
    "eventarc.googleapis.com/GoogleChannelConfig": Mapping(
        "google_eventarc_google_channel_config",
        True,
        import_id=lambda r: f"projects/{r.project}/locations/{r.location}/googleChannelConfig",
    ),
    # --- Observability ---------------------------------------------------
    "logging.googleapis.com/LogSink": Mapping(
        "google_logging_project_sink", True, import_id=lambda r: f"projects/{r.project}/sinks/{r.name}"
    ),
    "logging.googleapis.com/LogBucket": Mapping(
        "google_logging_project_bucket_config",
        True,
        import_id=lambda r: f"projects/{r.project}/locations/{r.location}/buckets/{r.name}",
    ),
    "logging.googleapis.com/LogMetric": Mapping(
        "google_logging_metric", True, import_id=lambda r: f"projects/{r.project}/metrics/{r.name}"
    ),
    "logging.googleapis.com/LogView": Mapping(
        "google_logging_log_view", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "monitoring.googleapis.com/AlertPolicy": Mapping(
        "google_monitoring_alert_policy", True, import_id=lambda r: f"projects/{r.project}/alertPolicies/{r.name}"
    ),
    "monitoring.googleapis.com/NotificationChannel": Mapping(
        "google_monitoring_notification_channel",
        True,
        import_id=lambda r: f"projects/{r.project}/notificationChannels/{r.name}",
    ),
    "monitoring.googleapis.com/UptimeCheckConfig": Mapping(
        "google_monitoring_uptime_check_config",
        True,
        import_id=lambda r: f"projects/{r.project}/uptimeCheckConfigs/{r.name}",
    ),
    "monitoring.googleapis.com/Dashboard": Mapping(
        "google_monitoring_dashboard", True, import_id=lambda r: f"projects/{r.project}/dashboards/{r.name}"
    ),
    "monitoring.googleapis.com/Snooze": Mapping(
        "google_monitoring_snooze", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    # --- AI / Vertex AI --------------------------------------------------
    # Not in the CAI page we scraped today but provider-supported; safe to
    # emit import blocks. Dataset/Endpoint/Model are the high-value ones.
    "aiplatform.googleapis.com/Endpoint": Mapping("google_vertex_ai_endpoint", True, _loc("endpoints")),
    "aiplatform.googleapis.com/Dataset": Mapping("google_vertex_ai_dataset", True, _loc("datasets")),
    "aiplatform.googleapis.com/Model": Mapping(
        "google_vertex_ai_model", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "aiplatform.googleapis.com/Featurestore": Mapping("google_vertex_ai_featurestore", True, _loc("featurestores")),
    "aiplatform.googleapis.com/Index": Mapping("google_vertex_ai_index", True, _loc("indexes")),
    "aiplatform.googleapis.com/IndexEndpoint": Mapping("google_vertex_ai_index_endpoint", True, _loc("indexEndpoints")),
    # --- Workflows / Apigee / Healthcare etc. ----------------------------
    "workflows.googleapis.com/Workflow": Mapping("google_workflows_workflow", True, _loc("workflows")),
    "apigee.googleapis.com/Organization": Mapping(
        "google_apigee_organization", True, import_id=lambda r: f"organizations/{r.name}"
    ),
    "apigee.googleapis.com/Environment": Mapping(
        "google_apigee_environment", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "apigee.googleapis.com/Instance": Mapping(
        "google_apigee_instance", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "healthcare.googleapis.com/Dataset": Mapping(
        "google_healthcare_dataset", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "healthcare.googleapis.com/FhirStore": Mapping(
        "google_healthcare_fhir_store", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "healthcare.googleapis.com/DicomStore": Mapping(
        "google_healthcare_dicom_store", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "healthcare.googleapis.com/Hl7V2Store": Mapping(
        "google_healthcare_hl7_v2_store", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "apigateway.googleapis.com/Api": Mapping(
        "google_api_gateway_api", True, import_id=lambda r: f"projects/{r.project}/locations/global/apis/{r.name}"
    ),
    "apigateway.googleapis.com/Gateway": Mapping("google_api_gateway_gateway", True, _loc("gateways")),
    "apigateway.googleapis.com/ApiConfig": Mapping(
        "google_api_gateway_api_config", True, import_id=lambda r: r.full_resource_name.lstrip("/")
    ),
    "apikeys.googleapis.com/Key": Mapping(
        "google_apikeys_key", True, import_id=lambda r: f"projects/{r.project}/locations/global/keys/{r.name}"
    ),
    "iap.googleapis.com/WebTypeAppEngine": Mapping("google_iap_web_type_app_engine_iam_policy", False),
    "firebase.googleapis.com/FirebaseProject": Mapping(
        "google_firebase_project", True, import_id=lambda r: f"projects/{r.project}"
    ),
    "metastore.googleapis.com/Service": Mapping("google_dataproc_metastore_service", True, _loc("services")),
    "metastore.googleapis.com/Federation": Mapping("google_dataproc_metastore_federation", True, _loc("federations")),
    "vpcaccess.googleapis.com/Connector": Mapping("google_vpc_access_connector", True, _loc("connectors")),
    # --- Service networking / service usage -------------------------------
    "servicenetworking.googleapis.com/Connection": Mapping(
        "google_service_networking_connection", False
    ),  # complex import
    "serviceusage.googleapis.com/Service": Mapping(
        "google_project_service", True, first_class=True, import_id=lambda r: f"{r.project}/{r.name}"
    ),
    # --- Notebooks --------------------------------------------------------
    "notebooks.googleapis.com/Instance": Mapping("google_notebooks_instance", True, _loc("instances")),
    "notebooks.googleapis.com/Runtime": Mapping("google_notebooks_runtime", True, _loc("runtimes")),
    # --- Transfer / backup -----------------------------------------------
    "storagetransfer.googleapis.com/TransferJob": Mapping(
        "google_storage_transfer_job", True, import_id=lambda r: f"{r.project}/{r.name}"
    ),
    "backupdr.googleapis.com/BackupVault": Mapping("google_backup_dr_backup_vault", True, _loc("backupVaults")),
    "backupdr.googleapis.com/BackupPlan": Mapping("google_backup_dr_backup_plan", True, _loc("backupPlans")),
    # --- Cloud SQL ancillary ---------------------------------------------
    "sqladmin.googleapis.com/Backup": Mapping("google_sql_database_instance", False),  # no direct tf resource
    "sqladmin.googleapis.com/BackupRun": Mapping("google_sql_database_instance", False),  # no direct tf resource
}


# Kubernetes asset types (k8s.io/*, apps.k8s.io/*, etc.) are NOT managed by
# the google provider — they need the kubernetes provider. Marking them as
# manual keeps the CAI inventory complete while making the limit explicit.
_K8S_PREFIXES = (
    "admissionregistration.k8s.io/",
    "apps.k8s.io/",
    "autoscaling.k8s.io/",
    "batch.k8s.io/",
    "extensions.k8s.io/",
    "gateway.networking.k8s.io/",
    "k8s.io/",
    "networking.k8s.io/",
    "policy.k8s.io/",
    "rbac.authorization.k8s.io/",
    "storage.k8s.io/",
)


@dataclass(frozen=True)
class Classified:
    resource: DiscoveredResource
    status: str  # "supported" | "importable" | "manual"
    tf_type: str | None
    import_id: str | None
    first_class: bool = False  # True if we ship a Jinja template for this type
    reason: str = ""  # Populated for ``manual`` status — why we can't manage it


# compute.Route next-hop types that google_compute_route cannot manage.
# Peering/Network/Hub routes are created implicitly by their parent resource,
# so emitting an import block for them would leave a dangling reference.
_UNMANAGEABLE_ROUTE_NEXT_HOPS = ("nextHopPeering", "nextHopNetwork", "nextHopHub")

# Google-managed service accounts — the account_id is either Google-assigned
# (numeric prefix breaks provider validation) or the SA is project-owned and
# can't be created/destroyed by Terraform at all. Match by email suffix.
_GOOGLE_MANAGED_SA_SUFFIXES = (
    "@developer.gserviceaccount.com",  # default compute SA (42608...-compute@...)
    "@appspot.gserviceaccount.com",  # default App Engine SA
    "@cloudservices.gserviceaccount.com",  # Google APIs SA
    "@system.gserviceaccount.com",  # system SA
)


def _is_google_managed_sa(resource: DiscoveredResource) -> bool:
    if resource.asset_type != "iam.googleapis.com/ServiceAccount":
        return False
    email = (resource.attributes.get("email") or "").lower()
    if email.endswith(_GOOGLE_MANAGED_SA_SUFFIXES):
        return True
    # Service agents: "service-<number>@gcp-sa-*.iam.gserviceaccount.com" and
    # any "<prefix>@gcp-sa-*.iam.gserviceaccount.com" address.
    local, sep, domain = email.partition("@")
    if not sep:
        return False
    if not (local.startswith("gcp-sa-") or local.startswith("service-")):
        return False
    if domain == "iam.gserviceaccount.com" or domain.endswith(".iam.gserviceaccount.com"):
        return True
    return False


def classify(resource: DiscoveredResource) -> Classified:
    # Explicit exclusion: Kubernetes API-discovered assets
    if resource.asset_type.startswith(_K8S_PREFIXES):
        return Classified(
            resource,
            "manual",
            None,
            None,
            False,
            reason="Kubernetes-API asset — managed by the cluster, not GCP IAM",
        )

    mapping = REGISTRY.get(resource.asset_type)
    if not mapping:
        return Classified(
            resource,
            "manual",
            None,
            None,
            False,
            reason=f"asset_type {resource.asset_type} has no TF mapping",
        )

    # Attribute-dependent exclusion: routes whose next-hop type isn't one of
    # the 5 that google_compute_route accepts.
    if resource.asset_type == "compute.googleapis.com/Route" and any(
        resource.attributes.get(k) for k in _UNMANAGEABLE_ROUTE_NEXT_HOPS
    ):
        return Classified(
            resource,
            "manual",
            None,
            None,
            False,
            reason="route next-hop type not supported by google_compute_route "
            "(peering/network/hub routes are created implicitly by their parent)",
        )

    # Google-managed service accounts can't be managed by google_service_account.
    if _is_google_managed_sa(resource):
        return Classified(
            resource,
            "manual",
            None,
            None,
            False,
            reason="Google-managed service account (default compute/app-engine/service agent) "
            "— account_id is Google-assigned and not manageable by Terraform",
        )

    if not mapping.importable or not mapping.import_id:
        # tf_type known but not importable (rare — complex/beta imports)
        return Classified(resource, "supported", mapping.tf_type, None, mapping.first_class)
    import_id = mapping.import_id(resource)
    return Classified(resource, "importable", mapping.tf_type, import_id, mapping.first_class)


def classify_all(resources: list[DiscoveredResource]) -> list[Classified]:
    return [classify(r) for r in resources]
