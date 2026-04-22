"""Tests for the CAI inventory client's scope filtering + per-type fallback.

Background: a single incompatible asset type in a CAI batch call fails the
whole request with InvalidArgument. Without the fallback, one bad type drops
every other type in the inventory too.
"""

from __future__ import annotations

from types import SimpleNamespace

from google.api_core.exceptions import InvalidArgument

from src.discovery.cai_client import (
    _ORG_ONLY_ASSET_TYPES,
    CloudAssetClient,
    _coerce_numbers,
    _filter_by_scope,
)

# ---------- scope filtering ----------


def test_filter_by_scope_drops_org_only_at_project_scope():
    asset_types = [
        "compute.googleapis.com/Network",
        "identity.accesscontextmanager.googleapis.com/AccessPolicy",
        "storage.googleapis.com/Bucket",
    ]
    compatible, dropped = _filter_by_scope(asset_types, "projects/p")
    assert compatible == [
        "compute.googleapis.com/Network",
        "storage.googleapis.com/Bucket",
    ]
    assert dropped == ["identity.accesscontextmanager.googleapis.com/AccessPolicy"]


def test_filter_by_scope_drops_org_only_at_folder_scope():
    compatible, dropped = _filter_by_scope(
        ["identity.accesscontextmanager.googleapis.com/AccessPolicy"],
        "folders/123",
    )
    assert compatible == []
    assert dropped == ["identity.accesscontextmanager.googleapis.com/AccessPolicy"]


def test_filter_by_scope_keeps_everything_at_org_scope():
    asset_types = list(_ORG_ONLY_ASSET_TYPES) + ["compute.googleapis.com/Network"]
    compatible, dropped = _filter_by_scope(asset_types, "organizations/42")
    assert compatible == asset_types
    assert dropped == []


# ---------- per-type fallback ----------


class _FakeAsset:
    """Minimal stand-in for google.cloud.asset_v1.Asset — enough for _to_resource.

    Leaves ``resource`` as None so the proto-plus ``to_dict`` path is skipped;
    these tests don't exercise attribute extraction, only the batch/fallback
    control flow.
    """

    def __init__(self, asset_type: str, name: str):
        self.asset_type = asset_type
        self.name = name
        self.resource = None
        self.iam_policy = None
        self.ancestors = []


def _make_client(list_assets_side_effect):
    """Build a CloudAssetClient whose underlying gRPC client uses the given side effect."""
    fake_grpc = SimpleNamespace(list_assets=list_assets_side_effect)
    client = CloudAssetClient.__new__(CloudAssetClient)
    client._client = fake_grpc
    return client


def test_per_type_fallback_isolates_incompatible_type():
    good = "compute.googleapis.com/Network"
    bad = "somethingelse.googleapis.com/Nope"

    def list_assets(request):
        types = list(request["asset_types"])
        # Batch call fails because `bad` is in it
        if len(types) > 1:
            raise InvalidArgument("type not supported at scope")
        # Per-type fallback
        if types == [good]:
            return iter([_FakeAsset(good, "//compute.googleapis.com/projects/p/global/networks/n")])
        if types == [bad]:
            raise InvalidArgument("type not supported at scope")
        raise AssertionError(f"unexpected types: {types}")

    client = _make_client(list_assets)
    report = client.inventory("projects/p", [good, bad], include_iam=False)

    assert len(report.resources) == 1
    assert report.resources[0].asset_type == good

    # Errors record the batch fallback and which specific type failed
    assert any(e.startswith("resource_batch_fallback") for e in report.errors)
    assert f"resource_incompatible:{bad}" in report.errors


def test_batch_success_no_fallback_called():
    """When the batch call succeeds, per-type retry must not run."""
    good_a = "compute.googleapis.com/Network"
    good_b = "storage.googleapis.com/Bucket"
    call_count = {"n": 0}

    def list_assets(request):
        call_count["n"] += 1
        types = list(request["asset_types"])
        assert set(types) == {good_a, good_b}, "fallback should not have run"
        return iter(
            [
                _FakeAsset(good_a, "//compute.googleapis.com/projects/p/global/networks/n"),
                _FakeAsset(good_b, "//storage.googleapis.com/p/b"),
            ]
        )

    client = _make_client(list_assets)
    report = client.inventory("projects/p", [good_a, good_b], include_iam=False)

    assert call_count["n"] == 1
    assert {r.asset_type for r in report.resources} == {good_a, good_b}
    assert report.errors == []


def test_coerce_numbers_converts_whole_floats_to_int():
    """Proto Struct stores numbers as double, so GCP int fields (priority,
    mtu, port) round-trip as floats. Terraform providers reject `65534.0`
    where an int is expected."""
    raw = {
        "priority": 65534.0,
        "mtu": 1460.0,
        "ports": ["22", "80"],
        "nested": {"cpu": 4.0, "utilization": 0.75},
        "list_of_floats": [1.0, 2.5, 3.0],
    }
    out = _coerce_numbers(raw)
    assert out["priority"] == 65534 and isinstance(out["priority"], int)
    assert out["mtu"] == 1460 and isinstance(out["mtu"], int)
    # Non-integer floats stay as float
    assert out["nested"]["utilization"] == 0.75
    assert isinstance(out["nested"]["utilization"], float)
    # Nested int-valued floats are coerced
    assert out["nested"]["cpu"] == 4 and isinstance(out["nested"]["cpu"], int)
    # Mixed list: ints coerced, non-ints preserved
    assert out["list_of_floats"] == [1, 2.5, 3]
    assert isinstance(out["list_of_floats"][0], int)
    assert isinstance(out["list_of_floats"][1], float)


def test_to_resource_unwraps_nested_repeated_fields_to_json_safe():
    """Regression: Firewall.sourceRanges arrived as RepeatedComposite and
    broke json.dumps inside the Jinja templates. _to_resource must return a
    fully native-Python attributes dict."""
    import json

    from google.cloud.asset_v1.types.assets import Asset
    from google.protobuf.struct_pb2 import Struct

    s = Struct()
    s.update(
        {
            "name": "allow-internal",
            "sourceRanges": ["10.0.0.0/8", "172.16.0.0/12"],
            "direction": "INGRESS",
            "labels": {"env": "dev"},
        }
    )
    asset = Asset()
    asset.asset_type = "compute.googleapis.com/Firewall"
    asset.name = "//compute.googleapis.com/projects/p/global/firewalls/allow-internal"
    asset.resource.data = s

    resource = CloudAssetClient._to_resource(asset, include_iam_policy=False)

    assert resource.attributes["sourceRanges"] == ["10.0.0.0/8", "172.16.0.0/12"]
    # The whole attrs dict must round-trip through json — this used to throw
    # TypeError: Object of type RepeatedComposite is not JSON serializable.
    json.dumps(resource.attributes)


def test_to_resource_normalises_location_from_self_link_url():
    """CAI sometimes returns ``data.region`` as a full self-link URL. We must
    store the short form so TF addresses stay short and unique per region."""
    from google.cloud.asset_v1.types.assets import Asset
    from google.protobuf.struct_pb2 import Struct

    s = Struct()
    s.update(
        {
            "name": "default",
            "region": "https://www.googleapis.com/compute/v1/projects/p/regions/us-central1",
            "ipCidrRange": "10.0.0.0/20",
        }
    )
    asset = Asset()
    asset.asset_type = "compute.googleapis.com/Subnetwork"
    asset.name = "//compute.googleapis.com/projects/p/regions/us-central1/subnetworks/default"
    asset.resource.data = s

    resource = CloudAssetClient._to_resource(asset, include_iam_policy=False)
    assert resource.location == "us-central1"


def test_to_resource_coerces_int_fields_from_proto_doubles():
    """Regression: priority came back as 65534.0; Terraform rejects a float
    where the schema expects int."""
    from google.cloud.asset_v1.types.assets import Asset
    from google.protobuf.struct_pb2 import Struct

    s = Struct()
    s.update({"name": "allow-icmp", "priority": 65534, "direction": "INGRESS"})
    asset = Asset()
    asset.asset_type = "compute.googleapis.com/Firewall"
    asset.name = "//compute.googleapis.com/projects/p/global/firewalls/allow-icmp"
    asset.resource.data = s

    resource = CloudAssetClient._to_resource(asset, include_iam_policy=False)
    assert resource.attributes["priority"] == 65534
    assert isinstance(resource.attributes["priority"], int)


def test_org_only_types_filtered_before_call():
    """Org-only types never reach CAI at project scope."""
    good = "compute.googleapis.com/Network"
    org_only = "identity.accesscontextmanager.googleapis.com/AccessPolicy"
    seen_types: list[list[str]] = []

    def list_assets(request):
        seen_types.append(list(request["asset_types"]))
        return iter([])

    client = _make_client(list_assets)
    report = client.inventory("projects/p", [good, org_only], include_iam=False)

    # org-only must not appear in any CAI request
    for types in seen_types:
        assert org_only not in types
    assert any("scope_filter_dropped" in e for e in report.errors)
