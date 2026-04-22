"""Tests for ``terraform_address`` — deterministic TF local names.

Regression: a project with a ``default`` subnetwork per region produced
colliding addresses (``networking_default``), failing ``terraform validate``
with "Duplicate resource".
"""

from __future__ import annotations

from src.discovery.models import DiscoveredResource
from src.generation.naming import terraform_address


def _subnet(region: str, name: str = "default") -> DiscoveredResource:
    return DiscoveredResource(
        provider="gcp",
        domain="networking",
        asset_type="compute.googleapis.com/Subnetwork",
        name=name,
        full_resource_name=f"//compute.googleapis.com/projects/p/regions/{region}/subnetworks/{name}",
        project="p",
        location=region,
        attributes={},
    )


def _global_network(name: str = "default") -> DiscoveredResource:
    return DiscoveredResource(
        provider="gcp",
        domain="networking",
        asset_type="compute.googleapis.com/Network",
        name=name,
        full_resource_name=f"//compute.googleapis.com/projects/p/global/networks/{name}",
        project="p",
        location="global",
        attributes={},
    )


def _sa(email_local: str) -> DiscoveredResource:
    return DiscoveredResource(
        provider="gcp",
        domain="iam",
        asset_type="iam.googleapis.com/ServiceAccount",
        name=email_local,
        full_resource_name=f"//iam.googleapis.com/projects/p/serviceAccounts/{email_local}@p.iam.gserviceaccount.com",
        project="p",
        location=None,
        attributes={},
    )


def test_regional_resources_with_same_name_get_distinct_addresses():
    us_central = terraform_address(_subnet("us-central1"))
    us_east = terraform_address(_subnet("us-east1"))
    assert us_central != us_east
    assert us_central == "networking_us_central1_default"
    assert us_east == "networking_us_east1_default"


def test_global_resources_omit_location_segment():
    addr = terraform_address(_global_network("default"))
    # Must not contain "global"; stays as the clean {domain}_{name}
    assert addr == "networking_default"


def test_non_located_resources_unchanged():
    """Project-scoped resources (SAs, custom roles) have no location."""
    addr = terraform_address(_sa("deploy-bot"))
    assert addr == "iam_deploy_bot"


def test_zonal_resources_include_zone():
    """GCE instances expose a zone like ``us-central1-a``."""
    inst = DiscoveredResource(
        provider="gcp",
        domain="compute",
        asset_type="compute.googleapis.com/Instance",
        name="web-1",
        full_resource_name="//compute.googleapis.com/projects/p/zones/us-central1-a/instances/web-1",
        project="p",
        location="us-central1-a",
        attributes={},
    )
    assert terraform_address(inst) == "compute_us_central1_a_web_1"


def test_address_stays_a_valid_hcl_identifier():
    """HCL local names must start with a letter; hyphens → underscores."""
    r = _subnet("us-central1", name="10-dash-start")
    addr = terraform_address(r)
    assert addr[0].isalpha()
    assert "-" not in addr
    assert len(addr) <= 120
