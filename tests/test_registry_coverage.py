"""Sanity tests on the REGISTRY to guard against regressions in coverage."""

from src.discovery.classifiers import REGISTRY, classify
from src.discovery.models import DiscoveredResource

_EXPECTED_COVERAGE = {
    # One representative per domain — guards against accidental deletion.
    "iam": [
        "iam.googleapis.com/ServiceAccount",
        "iam.googleapis.com/Role",
        "iam.googleapis.com/WorkloadIdentityPool",
        "cloudresourcemanager.googleapis.com/Project",
    ],
    "networking": [
        "compute.googleapis.com/Network",
        "compute.googleapis.com/Subnetwork",
        "compute.googleapis.com/Firewall",
        "compute.googleapis.com/BackendService",
        "compute.googleapis.com/UrlMap",
        "compute.googleapis.com/SecurityPolicy",
        "dns.googleapis.com/ManagedZone",
        "certificatemanager.googleapis.com/Certificate",
    ],
    "compute": [
        "compute.googleapis.com/Instance",
        "run.googleapis.com/Service",
        "run.googleapis.com/Job",
        "cloudfunctions.googleapis.com/Function",
        "container.googleapis.com/Cluster",
    ],
    "storage": [
        "storage.googleapis.com/Bucket",
        "bigquery.googleapis.com/Dataset",
        "sqladmin.googleapis.com/Instance",
        "spanner.googleapis.com/Instance",
        "firestore.googleapis.com/Database",
        "redis.googleapis.com/Instance",
        "alloydb.googleapis.com/Cluster",
    ],
    "security": [
        "cloudkms.googleapis.com/KeyRing",
        "cloudkms.googleapis.com/CryptoKey",
        "secretmanager.googleapis.com/Secret",
        "privateca.googleapis.com/CaPool",
        "binaryauthorization.googleapis.com/Policy",
    ],
    "devops": [
        "artifactregistry.googleapis.com/Repository",
        "cloudbuild.googleapis.com/BuildTrigger",
        "clouddeploy.googleapis.com/DeliveryPipeline",
        "logging.googleapis.com/LogSink",
        "monitoring.googleapis.com/AlertPolicy",
    ],
    "messaging_and_events": [
        "pubsub.googleapis.com/Topic",
        "pubsub.googleapis.com/Subscription",
        "cloudtasks.googleapis.com/Queue",
        "eventarc.googleapis.com/Trigger",
    ],
    "ai": [
        "aiplatform.googleapis.com/Endpoint",
        "aiplatform.googleapis.com/Dataset",
    ],
    "other": [
        "workflows.googleapis.com/Workflow",
        "apigateway.googleapis.com/Api",
        "firebase.googleapis.com/FirebaseProject",
    ],
}


def test_registry_size_floor():
    # Protects against accidental truncation of REGISTRY
    assert len(REGISTRY) >= 80, f"REGISTRY shrank to {len(REGISTRY)} entries"


def test_expected_asset_types_are_covered():
    missing = []
    for domain, types in _EXPECTED_COVERAGE.items():
        for t in types:
            if t not in REGISTRY:
                missing.append(f"{domain}:{t}")
    assert not missing, f"REGISTRY missing: {missing}"


def test_k8s_resources_are_manual():
    # Cluster-internal k8s.io objects belong to the kubernetes provider, not google.
    r = DiscoveredResource(
        provider="gcp",
        domain="other",
        asset_type="k8s.io/Pod",
        name="my-pod",
        full_resource_name="//k8s.io/my-pod",
    )
    assert classify(r).status == "manual"

    r2 = DiscoveredResource(
        provider="gcp",
        domain="other",
        asset_type="apps.k8s.io/Deployment",
        name="web",
        full_resource_name="//apps.k8s.io/deployments/web",
    )
    assert classify(r2).status == "manual"


def test_first_class_flag_is_set_for_templated_resources():
    # Only these have Jinja templates today. Keep this list in sync with
    # src/generation/templates/ contents.
    first_class = {asset for asset, m in REGISTRY.items() if m.first_class}
    expected_first_class = {
        "iam.googleapis.com/ServiceAccount",
        "iam.googleapis.com/Role",
        "cloudresourcemanager.googleapis.com/Project",
        "compute.googleapis.com/Network",
        "compute.googleapis.com/Subnetwork",
        "compute.googleapis.com/Firewall",
        "compute.googleapis.com/Route",
        "compute.googleapis.com/Router",
        "dns.googleapis.com/ManagedZone",
        "compute.googleapis.com/Instance",
        "compute.googleapis.com/InstanceGroupManager",
        "run.googleapis.com/Service",
    }
    assert expected_first_class.issubset(first_class)


def test_import_id_canonical_examples():
    """Each type here has a canonical form verified against google provider 7.x docs."""
    samples = {
        "storage.googleapis.com/Bucket": (
            DiscoveredResource(
                provider="gcp",
                domain="storage",
                asset_type="storage.googleapis.com/Bucket",
                name="my-bucket",
                full_resource_name="//storage.googleapis.com/my-bucket",
                project="proj-a",
            ),
            "proj-a/my-bucket",
        ),
        "pubsub.googleapis.com/Topic": (
            DiscoveredResource(
                provider="gcp",
                domain="other",
                asset_type="pubsub.googleapis.com/Topic",
                name="events",
                full_resource_name="//pubsub.googleapis.com/projects/proj-a/topics/events",
                project="proj-a",
            ),
            "projects/proj-a/topics/events",
        ),
        "secretmanager.googleapis.com/Secret": (
            DiscoveredResource(
                provider="gcp",
                domain="security",
                asset_type="secretmanager.googleapis.com/Secret",
                name="api-key",
                full_resource_name="//secretmanager.googleapis.com/projects/proj-a/secrets/api-key",
                project="proj-a",
            ),
            "projects/proj-a/secrets/api-key",
        ),
        "bigquery.googleapis.com/Dataset": (
            DiscoveredResource(
                provider="gcp",
                domain="storage",
                asset_type="bigquery.googleapis.com/Dataset",
                name="analytics",
                full_resource_name="//bigquery.googleapis.com/projects/proj-a/datasets/analytics",
                project="proj-a",
            ),
            "projects/proj-a/datasets/analytics",
        ),
        "sqladmin.googleapis.com/Instance": (
            DiscoveredResource(
                provider="gcp",
                domain="storage",
                asset_type="sqladmin.googleapis.com/Instance",
                name="prod-db",
                full_resource_name="//sqladmin.googleapis.com/projects/proj-a/instances/prod-db",
                project="proj-a",
            ),
            "projects/proj-a/instances/prod-db",
        ),
        "cloudkms.googleapis.com/KeyRing": (
            DiscoveredResource(
                provider="gcp",
                domain="security",
                asset_type="cloudkms.googleapis.com/KeyRing",
                name="prod-ring",
                full_resource_name="//cloudkms.googleapis.com/projects/proj-a/locations/us-central1/keyRings/prod-ring",
                project="proj-a",
                location="us-central1",
            ),
            "projects/proj-a/locations/us-central1/keyRings/prod-ring",
        ),
    }
    for asset_type, (resource, expected_id) in samples.items():
        result = classify(resource)
        assert result.status == "importable", f"{asset_type} not importable"
        assert result.import_id == expected_id, f"{asset_type}: {result.import_id!r} != {expected_id!r}"
