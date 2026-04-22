# ai-tf

[![CI](https://github.com/erayguner/tf-out/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/erayguner/tf-out/actions/workflows/ci.yml)
[![CodeQL](https://github.com/erayguner/tf-out/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/erayguner/tf-out/actions/workflows/codeql.yml)
[![Security Policy](https://img.shields.io/badge/security-policy-informational?logo=github)](SECURITY.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue?logo=python&logoColor=white)](pyproject.toml)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-%23FE5196?logo=conventionalcommits&logoColor=white)](https://www.conventionalcommits.org)
[![Terraform](https://img.shields.io/badge/Terraform-%E2%89%A51.14-7B42BC?logo=terraform&logoColor=white)](https://www.terraform.io)

**ai-tf reverse-engineers a live GCP project into Terraform.**

It walks Cloud Asset Inventory, classifies every resource against the Terraform provider, writes HCL + `import {}` blocks, builds a dependency graph, and validates the output in an isolated sandbox project — all with an append-only audit log and human-in-the-loop gates on risky actions.

## What you get

Run the pipeline once against a project. The output is a `generated-terraform/` directory that:

- `terraform init` parses without errors,
- `terraform validate` reports success,
- `terraform plan` (in a sandbox project) imports existing state rather than recreating it,
- lists anything it can't manage in `MANUAL_RESOURCES.md` with a specific reason (peering route, Google-managed SA, unsupported asset type, …).

## How it works (one pass through the pipeline)

```
DiscoveryAgent    → scans Cloud Asset Inventory at your chosen scope
ClassificationAgent → maps each asset_type to a TF type; marks manual/supported/importable
GovernanceAgent   → applies deny rules, flags manual resources, routes blockers through HITL
TerraformAgent    → renders Jinja templates per domain → project.tf, iam.tf, networking.tf, …
DependencyAgent   → builds a networkx graph (resource → parent/region/network)
ValidationAgent   → provisions a sandbox, runs init/validate/plan/apply/destroy, tears down
ReasoningBankAgent → (optional) stores the run's trajectory for future runs to learn from
```

Each stage writes to a chained SHA-256 audit log. Any blocking policy violation or sandbox apply pauses for HITL approval — `AI_TF_APPROVE=yes` satisfies the gate in CI.

## Quickstart

### Local dev (fastest — uses your gcloud ADC)

ai-tf uses [**uv**](https://docs.astral.sh/uv/) for dependency and environment management. Install uv once (`brew install uv` / `curl -LsSf https://astral.sh/uv/install.sh | sh`), then:

```bash
uv sync                                      # creates .venv, installs pinned deps from uv.lock

gcloud auth application-default login

# Tell tf-out what to scan
$EDITOR config/settings.yaml
#   project.scope_id       → projects/<your-project>
#   auth.allow_adc         → true   (local only)
#   validation.sandbox_project_id → projects/<an-empty-project>  (skip if you don't need validate)

uv run ai-tf inspect                         # sanity-check your settings
uv run ai-tf run --config config/settings.yaml
```

`uv run` invokes commands inside the project venv without an explicit `source .venv/bin/activate`. Activate it manually if you prefer: `source .venv/bin/activate`.

### Production posture (WIF + CI)

Follow [docs/runbook.md](docs/runbook.md) — creates the pool, provider, SA bindings, and the GitHub Actions workflow. WIF is the default; ADC requires an explicit `allow_adc: true` opt-in.

## Coverage

**200+ GCP resource types** across IAM, networking, compute, storage, security, devops, messaging, observability, AI/ML, API management, and project-level config. Two tiers:

- **First-class** (≈14 templates) — ship full Jinja HCL. `terraform apply` runs clean after `import`.
- **Import-only** (the rest) — emit a canonical `import {}` block; Terraform synthesises HCL via `terraform plan -generate-config-out=auto_generated.tf` (1.5+).

ai-tf skips Google-managed resources that Terraform can't legally own: `k8s.io/*`, default compute/App Engine SAs, service agents, peering/network/hub routes. They land in `MANUAL_RESOURCES.md` with a reason.

Full matrix: [docs/RESOURCE_COVERAGE.md](docs/RESOURCE_COVERAGE.md). Provider verification: [docs/IMPORT_REVIEW.md](docs/IMPORT_REVIEW.md).

## Layout

```
src/
  agents/        One Python class per pipeline stage. orchestrator.py wires them in order.
  auth/          WIF (preferred) + ADC (opt-in) credential resolver.
  discovery/     CAI client, typed resource model, classifier REGISTRY.
  generation/    Jinja templates (project / iam / networking / compute) + writer + naming.
  graph/         networkx dependency graph with DOT + JSON export.
  validation/    Hermetic terraform subprocess runner + sandbox lifecycle with try/finally destroy.
  governance/    Audit log (chained + signed), policy engine, HITL gate, kill-switch.
  core/          Tool governor, filter stack, AgentTrace.
  mcp/           MCP tool surface (one tool: ai_tf_run_pipeline).
config/          settings.yaml + WIF config template.
tests/           pytest suite (87 tests, no network).
docs/            architecture / runbook / governance / coverage.
generated-terraform/   Output. Wiped and rewritten every run. Gitignored.
```

## Extending coverage

Add a new asset type:

1. Append the asset type to `config/settings.yaml → discovery.asset_types`.
2. Add a row to `REGISTRY` in `src/discovery/classifiers.py` with `tf_type`, `import_id` lambda, and `first_class=True` if you're also shipping a template.
3. (Optional, for first-class) Add a block to the matching `src/generation/templates/<domain>.tf.j2`.

Add a whole new domain: also add it to `_DOMAIN_TEMPLATE` in `src/generation/hcl_writer.py`, to `_DOMAIN_PREFIX` in `src/discovery/cai_client.py`, and to the `Domain` literal in `src/discovery/models.py`.

## Docs

- [docs/architecture.md](docs/architecture.md) — pipeline internals and extension points
- [docs/runbook.md](docs/runbook.md) — operator runbook (WIF, halt, audit, HITL, sidecar)
- [docs/governance.md](docs/governance.md) — policy engine, audit log, HITL, kill-switch
- [docs/RESOURCE_COVERAGE.md](docs/RESOURCE_COVERAGE.md) — the full asset-type → TF matrix
