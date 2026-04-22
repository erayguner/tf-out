# Architecture

## Design goals

1. **The pipeline runs without an LLM.** Every stage is a pure Python function over typed models. The ADK runtime wraps the whole pipeline as one deterministic tool for natural-language summaries; tests and CI run without any LLM call.
2. **The core is provider-agnostic.** `DiscoveredResource` is a shared shape. Adding AWS means writing an AWS discovery client that emits the same model; classification, generation, and graph reuse unchanged.
3. **No output ships without validation.** ai-tf marks nothing "production-ready" until `terraform init/validate/plan/apply/destroy` passes in an isolated sandbox project.
4. **Every action lands in the audit log.** Each agent writes actor, action, target, outcome, and rationale to the chained SHA-256 audit log.

## Pipeline

```
DiscoveryAgent         Cloud Asset Inventory — list assets + IAM policies at scope
      ↓
ClassificationAgent    asset_type → TF type via REGISTRY; attaches reason to manual
      ↓
(hydrate_prior_runs)   optional — pulls similar past trajectories from ReasoningBank
      ↓
GovernanceAgent        policy rules + HITL gate on denies
      ↓
TerraformAgent         Jinja per domain → project.tf / iam.tf / networking.tf / compute.tf;
                       writes imports.tf, import.sh, GENERATE_CONFIG.md; runs terraform fmt
      ↓
DependencyAgent        networkx graph → graph.json + graph.dot
      ↓
ValidationAgent        hermetic terraform subprocess in sandbox; try/finally destroy
      ↓
ReasoningBankAgent     (optional) persists the trajectory for future runs to learn from
```

`src/agents/orchestrator.py::build_pipeline` wires these in order. Each stage accepts and returns the same `PipelineContext`, so adding a stage is a one-line insertion.

## Key types

| Type | Where | Purpose |
|---|---|---|
| `PipelineContext` | `agents/orchestrator.py` | Dataclass threaded through every agent. Stages mutate in place. |
| `DiscoveredResource` | `discovery/models.py` | One resource record. `stable_id()` is the graph key and TF local-name seed. |
| `Classified` | `discovery/classifiers.py` | `(resource, status, tf_type, import_id, first_class, reason)`. `status ∈ {supported, importable, manual}`. `reason` explains *why* we marked something manual (e.g. "route next-hop type not supported"). |
| `PolicyViolation` | `governance/policies.py` | `(rule, resource, detail, severity)`. `severity=deny` blocks the run unless HITL waives it. |
| `SandboxResult` | `validation/sandbox.py` | Which lifecycle steps passed. `fully_validated` is the output gate. |

## Domains and templates

A "domain" groups asset types for HCL rendering. The CAI client tags each asset (`_DOMAIN_PREFIX` in `discovery/cai_client.py`); the HCL writer looks up one Jinja template per domain (`_DOMAIN_TEMPLATE` in `generation/hcl_writer.py`).

| Domain | Template | Covers |
|---|---|---|
| `project` | `project.tf.j2` | `google_project`, `google_project_service` (enabled APIs) |
| `iam` | `iam.tf.j2` | service accounts, custom roles, IAM policy bindings |
| `networking` | `networking.tf.j2` | VPC, subnet, firewall, route, DNS zone |
| `compute` | `compute.tf.j2` | GCE instances, Cloud Run |

Resources in domains without a template (storage, security, devops, …) still get an `import {}` block — operators run `terraform plan -generate-config-out` to synthesise the resource body.

## Cross-cutting modules

- `core/tool_governor.py` — single enforcement point. `governed_call()` wraps every tool: kill-switch → allow-list → filter stack → budget → audit.
- `core/agent_trace.py` — per-run trace with `correlation_id` / `causation_id` / `parent_step_id`, Markdown `replay()`, OTel export.
- `core/filters.py` — scans tool I/O for secrets, PII, injection phrases.
- `governance/audit.py` — chained SHA-256 log with `verify_chain()`, `write_manifest()`, `export_signed()`.
- `governance/hitl.py` — HMAC-signed approval tokens with TTL, plus env and TTY fallbacks.
- `governance/kill_switch.py` — file + env halt channels consulted on every tool call.
- `memory/reasoning_bank.py` — optional trajectory store. Fail-open HTTP client to the sidecar with circuit breaker and pre-filter.
- `sidecar/` — Node AgentDB service (loopback bind, bearer-token auth, scalar quantization, HNSW index).

## ADK integration (`agents/adk_bridge.py`)

`build_adk_root(settings)` returns an `LlmAgent` (model `gemini-2.5-pro`) with a single `FunctionTool`: `run_ai_tf_pipeline`. The tool runs the full deterministic pipeline and returns a JSON summary; the model's only job is to call the tool once and narrate the result for a human reviewer.

The SDK is an optional dep — importing `adk_bridge` without `google-adk` installed raises at `build_adk_root` call time, not at import time. There is deliberately no CLI command for this path: the ADK `Runner` API is too flexible to lock into a flag. Drive it from your own script per [docs/runbook.md](runbook.md).

## MCP surface (`mcp/tools.py`)

External orchestrators (including Claude Code) trigger the pipeline via one MCP tool, `ai_tf_run_pipeline`. It accepts a config path and non-interactive flag and returns a structured JSON summary (run_id, audit log path, violations, validation steps).

## Extension contract

### Add a new asset type

1. Append the asset type to `config/settings.yaml → discovery.asset_types`.
2. Add a row to `REGISTRY` in `src/discovery/classifiers.py`: `tf_type`, `importable`, `import_id` lambda, and `first_class=True` when you're also shipping a template.

### Add a new domain (e.g. `storage`)

Do the asset-type steps above, plus:

3. Add a `<domain>.tf.j2` template under `src/generation/templates/`.
4. Register it in `_DOMAIN_TEMPLATE` in `src/generation/hcl_writer.py`.
5. Tag the asset prefix in `_DOMAIN_PREFIX` in `src/discovery/cai_client.py`.
6. Add the domain name to the `Domain` literal in `src/discovery/models.py`.
7. (Optional) Extract dependency edges in `src/graph/dependency.py`.
8. Add a test file under `tests/`.

### Add a new cloud provider

1. Create `src/discovery/<provider>_client.py` that yields `DiscoveredResource` with `provider="<name>"`.
2. Add provider-specific `asset_type → tf_type` rows to `REGISTRY` (or split the registry per provider).
3. Wire a second `DiscoveryAgent` into `build_pipeline`.
