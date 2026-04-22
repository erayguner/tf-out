from src.discovery.classifiers import classify, classify_all


def test_network_is_supported_and_importable(sample_network):
    result = classify(sample_network)
    assert result.tf_type == "google_compute_network"
    assert result.status == "importable"
    # Canonical form per google provider 7.x docs
    assert result.import_id == "projects/proj-a/global/networks/vpc-app"


def test_subnet_import_id_is_regional(sample_subnet):
    result = classify(sample_subnet)
    assert result.tf_type == "google_compute_subnetwork"
    assert result.import_id == "projects/proj-a/regions/us-west1/subnetworks/subnet-west"


def test_unknown_asset_type_is_manual():
    from src.discovery.models import DiscoveredResource

    exotic = DiscoveredResource(
        provider="gcp",
        domain="other",
        asset_type="unknown.googleapis.com/Foo",
        name="x",
        full_resource_name="//unknown/x",
    )
    result = classify(exotic)
    assert result.status == "manual"
    assert result.tf_type is None


def test_classify_all_returns_one_per_input(sample_report):
    out = classify_all(sample_report.resources)
    assert len(out) == len(sample_report.resources)


def _route(name: str, **next_hop) -> "DiscoveredResource":
    from src.discovery.models import DiscoveredResource

    return DiscoveredResource(
        provider="gcp",
        domain="networking",
        asset_type="compute.googleapis.com/Route",
        name=name,
        full_resource_name=f"//compute.googleapis.com/projects/p/global/routes/{name}",
        project="p",
        location="global",
        attributes=next_hop,
    )


def test_route_with_manageable_next_hop_is_importable():
    """Regression: google_compute_route accepts gateway/ilb/instance/ip/vpn_tunnel."""
    for hop in (
        {"nextHopGateway": "https://.../default-internet-gateway"},
        {"nextHopIp": "10.0.0.1"},
        {"nextHopInstance": "https://.../instances/vm-1"},
        {"nextHopIlb": "https://.../forwardingRules/ilb-1"},
        {"nextHopVpnTunnel": "https://.../vpnTunnels/t-1"},
    ):
        result = classify(_route("r", **hop))
        assert result.status == "importable", f"expected importable for {hop}"
        assert result.tf_type == "google_compute_route"


def test_route_with_peering_next_hop_is_manual():
    """Regression: peering/network/hub routes are not manageable by
    google_compute_route — classifying them as importable produced an import
    block pointing at a resource that doesn't exist, breaking terraform init."""
    for hop in (
        {"nextHopPeering": "peering-1"},
        {"nextHopNetwork": "https://.../networks/n"},
        {"nextHopHub": "https://.../hubs/h"},
    ):
        result = classify(_route("r", **hop))
        assert result.status == "manual", f"expected manual for {hop}"
        assert result.import_id is None
        # Classifier now attaches an accurate reason (was misleading "no TF mapping")
        assert "next-hop" in result.reason.lower()


def _sa(email: str):
    from src.discovery.models import DiscoveredResource

    return DiscoveredResource(
        provider="gcp",
        domain="iam",
        asset_type="iam.googleapis.com/ServiceAccount",
        name=email.split("@")[0],
        full_resource_name=f"//iam.googleapis.com/projects/p/serviceAccounts/{email}",
        project="p",
        attributes={"email": email},
    )


def test_google_managed_default_compute_sa_is_manual():
    """Regression: account_id "42608262299-compute" fails the provider's
    regex `^[a-z](...)`. Google-managed SAs can't be created/managed by TF."""
    result = classify(_sa("42608262299-compute@developer.gserviceaccount.com"))
    assert result.status == "manual"
    assert "google-managed" in result.reason.lower()


def test_google_managed_service_agent_sa_is_manual():
    """service-<n>@gcp-sa-*.iam.gserviceaccount.com are service agents."""
    result = classify(_sa("service-42608262299@gcp-sa-cloudkms.iam.gserviceaccount.com"))
    assert result.status == "manual"


def test_google_managed_appspot_sa_is_manual():
    """Default App Engine SA."""
    result = classify(_sa("example-project-12345@appspot.gserviceaccount.com"))
    assert result.status == "manual"


def test_user_created_sa_is_still_importable():
    """Must NOT flag normal user-created SAs — they're exactly what we want to manage."""
    result = classify(_sa("deploy-bot@my-project.iam.gserviceaccount.com"))
    assert result.status == "importable"
    assert result.tf_type == "google_service_account"
