# Import-format review (google provider 7.28.0)

Cross-checked `src/discovery/classifiers.py::REGISTRY` against the official
Terraform Registry via the Terraform MCP on 2026-04-20. Provider version at
review time: **hashicorp/google 7.28.0**.

## Summary

- Every `import_id` lambda produces a form **accepted** by the provider.
- Previously we mixed canonical (`projects/.../global/networks/...`) and
  shorthand (`{project}/{name}`). Now all canonical.
- Import emission now defaults to **Terraform 1.5+ `import { }` HCL blocks**
  (plannable, reviewable, idempotent); `import.sh` kept as break-glass.

## Verified formats

| asset_type | tf_type | Emitted `id` (canonical) | Provider-accepted? |
|---|---|---|---|
| `compute.googleapis.com/Network` | `google_compute_network` | `projects/{p}/global/networks/{n}` | ✓ (canonical) |
| `compute.googleapis.com/Subnetwork` | `google_compute_subnetwork` | `projects/{p}/regions/{r}/subnetworks/{n}` | ✓ (canonical) |
| `compute.googleapis.com/Firewall` | `google_compute_firewall` | `projects/{p}/global/firewalls/{n}` | ✓ (canonical) |
| `compute.googleapis.com/Route` | `google_compute_route` | `projects/{p}/global/routes/{n}` | ✓ (canonical) |
| `compute.googleapis.com/Router` | `google_compute_router` | `projects/{p}/regions/{r}/routers/{n}` | ✓ (canonical) |
| `compute.googleapis.com/Instance` | `google_compute_instance` | `projects/{p}/zones/{z}/instances/{n}` | ✓ (canonical) |
| `compute.googleapis.com/InstanceGroupManager` | `google_compute_instance_group_manager` | `projects/{p}/zones/{z}/instanceGroupManagers/{n}` | ✓ (canonical) |
| `run.googleapis.com/Service` | `google_cloud_run_v2_service` | `projects/{p}/locations/{l}/services/{n}` | ✓ (canonical) |
| `dns.googleapis.com/ManagedZone` | `google_dns_managed_zone` | `projects/{p}/managedZones/{n}` | ✓ (canonical) |
| `iam.googleapis.com/ServiceAccount` | `google_service_account` | `projects/{p}/serviceAccounts/{email}` | ✓ (only accepted) |
| `iam.googleapis.com/Role` | `google_project_iam_custom_role` | `projects/{p}/roles/{role_id}` | ✓ (canonical) |
| `cloudresourcemanager.googleapis.com/Project` | `google_project` | `{project_id}` | ✓ (only accepted) |

## Issues fixed in this pass

1. **Provider pin was stale.** `~> 6.0` → `~> 7.0`. Aligns with the spec's
   "latest provider versions (2026 aligned)" requirement.
2. **`terraform_version` pinned to 1.14.0.** `>= 1.14.0`. Guarantees
   `import { }` blocks (1.5+), `identity { }` blocks (1.12+), and current
   `plan -generate-config-out` semantics.
3. **`google_service_account.account_id` was wrong.** The template emitted
   `uniqueId` (21-digit numeric), which fails the required regex
   `[a-z]([-a-z0-9]*[a-z0-9])`. Fixed to derive from the local-part of the
   SA email. `terraform apply` now succeeds.
4. **Import emission upgraded.** Previously `import.sh` (legacy CLI) only;
   now also `imports.tf` with declarative `import { }` blocks. `import.sh`
   retained as a fallback.
5. **Canonical IDs everywhere.** Several resources were using shorthand
   (`{project}/{name}`); switched to the explicit canonical forms. Both
   work, but canonical is unambiguous across region/zone overlap and
   survives provider upgrades.

## Recommended operator workflow

```bash
cd generated-terraform/
terraform init
terraform plan    # proposes imports + any drift against current state
# review the plan like any other PR
terraform apply
# optional: delete imports.tf after successful apply and commit
```

### Alternative: generate-config-out

For resources we classify as `manual` (no TF coverage in REGISTRY),
operators can leverage Terraform 1.5+'s `-generate-config-out`:

```bash
# Add import blocks by hand for unmapped resources
terraform plan -generate-config-out=generated.tf
# edit generated.tf into proper modules
```

This is an extension path documented in `docs/architecture.md`.

## Identity blocks (Terraform 1.12+)

google provider 7.x also supports `identity { }` blocks for imports (key-
based rather than ID-string-based). Not emitted by default because it
requires a Terraform 1.12+ floor and adds per-resource knowledge of which
fields are identity components. Tracked as an L2 enhancement.

## References

All checked via the Terraform Registry MCP (`hashicorp/google` v7.28.0):

- `google_compute_network` — provider_doc_id 12003080
- `google_compute_subnetwork` — 12003163
- `google_compute_firewall` — 12003043
- `google_service_account` — 12003435
- `google_project_iam_custom_role` — 12003431
- `google_cloud_run_v2_service` — 12002991

Provider capabilities checked: `get_latest_provider_version(hashicorp, google)` → 7.28.0.
