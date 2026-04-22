"""Shared fixtures. Builds fake DiscoveredResource objects — no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.discovery.models import DiscoveredResource, DiscoveryReport


@pytest.fixture
def sample_network() -> DiscoveredResource:
    return DiscoveredResource(
        provider="gcp",
        domain="networking",
        asset_type="compute.googleapis.com/Network",
        name="vpc-app",
        full_resource_name="//compute.googleapis.com/projects/proj-a/global/networks/vpc-app",
        project="proj-a",
        location="global",
        attributes={"autoCreateSubnetworks": False, "routingConfig": {"routingMode": "REGIONAL"}},
    )


@pytest.fixture
def sample_subnet() -> DiscoveredResource:
    return DiscoveredResource(
        provider="gcp",
        domain="networking",
        asset_type="compute.googleapis.com/Subnetwork",
        name="subnet-west",
        full_resource_name="//compute.googleapis.com/projects/proj-a/regions/us-west1/subnetworks/subnet-west",
        project="proj-a",
        location="us-west1",
        attributes={
            "ipCidrRange": "10.0.0.0/24",
            "network": "//compute.googleapis.com/projects/proj-a/global/networks/vpc-app",
        },
    )


@pytest.fixture
def sample_sa() -> DiscoveredResource:
    return DiscoveredResource(
        provider="gcp",
        domain="iam",
        asset_type="iam.googleapis.com/ServiceAccount",
        name="app-sa",
        full_resource_name="//iam.googleapis.com/projects/proj-a/serviceAccounts/app-sa@proj-a.iam.gserviceaccount.com",
        project="proj-a",
        attributes={"email": "app-sa@proj-a.iam.gserviceaccount.com", "displayName": "App SA"},
    )


@pytest.fixture
def sample_report(sample_network, sample_subnet, sample_sa) -> DiscoveryReport:
    return DiscoveryReport(
        scope="projects/proj-a",
        resources=[sample_network, sample_subnet, sample_sa],
    )


@pytest.fixture
def tmp_outdir(tmp_path: Path) -> Path:
    d = tmp_path / "out"
    d.mkdir()
    return d
