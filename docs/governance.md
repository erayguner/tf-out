# Governance & security model

## Principles (2026 agentic standards)

1. **Every decision hits the audit log.** Each agent writes actor, action, target, outcome, and rationale. Nothing implicit, nothing off-record.
2. **The pipeline stays deterministic; LLM calls only narrate.** Discovery, classification, graph, validation — all pure Python. The ADK runtime runs one LLM call at the end to summarise the run for a human reviewer.
3. **Every SA gets least privilege.** The discovery SA holds read-only roles on the scope. The sandbox SA holds write roles on the sandbox project only. Apply against production requires a different SA and explicit HITL.
4. **No secrets enter source.** tf-out uses short-lived WIF tokens by default. The repo commits config *paths* — never values.
5. **A human can step in on every mutation.** `HumanGate` guards blocking policy denials and every sandbox apply. CI pre-approves via `AI_TF_APPROVE=yes`; the approval event captures approver + reason.

## Audit log format (chained, tamper-evident)

Each line is a JSON event with SHA-256 chaining (`prev_hash` + `hash`, genesis = 64 zeros). Any edit to a past entry invalidates every following hash.

```json
{
  "timestamp": "2026-04-20T12:34:56Z",
  "run_id": "20260420T123456Z-a1b2c3d4",
  "seq": 7,
  "actor": "discovery",
  "action": "scan_completed",
  "target": "projects/my-proj",
  "outcome": "success",
  "rationale": "resources=42 errors=0",
  "data": { "resources": 42, "errors": [] },
  "prev_hash": "…", "hash": "…"
}
```

Writes go through `fsync`. At run end `AuditLog.write_manifest()` emits `<run_id>.audit.manifest.json` — HMAC-SHA256 (dev, `AI_TF_AUDIT_HMAC_KEY`) or Ed25519 (prod, `AI_TF_AUDIT_ED25519_PEM`) signed.

Ship to Cloud Logging with a Fluent Bit / OpenTelemetry sidecar. Store manifests out of band to retain chain-of-custody. The audit-log directory is **not** committed.

## Policy engine

Rules live in `src/governance/policies.py`. Each rule is a pure function `(classified, cfg) -> [PolicyViolation]`. Severity is `deny` (blocks) or `warn` (logged).

Current rules:

| Rule | Severity | Check |
|---|---|---|
| `deny_public_iam` | deny | Any binding to `allUsers`/`allAuthenticatedUsers` |
| `max_resources_per_run` | deny | `len(classified) > cfg.max_resources_per_run` |
| `manual_resource` | warn | The classifier marked the resource manual. The violation's `detail` quotes the classifier's specific reason — e.g. "route next-hop type not supported by google_compute_route", "Google-managed service account", or the generic "asset_type X has no TF mapping". |

Adding a rule is three lines: write the function, append it to `_RULES`. No registry, no plugin system — deliberate.

## HITL decisions

`src/governance/hitl.py` accepts three channels:

1. **HMAC-signed token** (preferred). Set `AI_TF_APPROVAL_TOKEN` to a token minted with `mint_token(run_id, action, decision, approver, reason, ttl_seconds)`. The runner verifies signature (`AI_TF_HITL_KEY`), action match, run_id, and expiry.
2. **Env short-circuit** (CI). Set `AI_TF_APPROVE=yes`, `AI_TF_APPROVER`, `AI_TF_APPROVAL_REASON`. All three land in the audit event.
3. **Interactive TTY**. The gate prompts on stderr and reads `y/N` + reason from stdin.

Default triggers:

- **Blocking policy violation** — governance agent requests an override.
- **Sandbox apply** — validation agent requests approval before mutating.

Add new triggers by listing them in `governance.hitl_required_for` and calling `ctx.hitl.request(action, summary, run_id)` from the relevant agent. Every decision writes a `HumanOverrideStep` into the AgentTrace.

## Kill-switch

Halt a run in <1 minute without killing the process:

- **File**: write `kill/<run_id>.halt` with `{"reason":"..."}`. Use `all.halt` to halt every run.
- **Env**: `AI_TF_HALT=<run_id>` (or `*`) short-circuits the current process.

The governor consults both before every tool call. The first observed halt is itself audited and is sticky until the operator clears the file. See `src/governance/kill_switch.py`.

## Tool governor

`src/core/tool_governor.py` is the single enforcement point (framework §4). Every tool call passes through `governed_call()`, which:

1. Checks the kill-switch.
2. Resolves the tool against the named allow-list; unlisted tools deny with `default_allow=False`.
3. Runs `FilterStack.scan()` on inputs (PII + secret patterns + injection heuristic). Secret findings hard-block; PII is audited.
4. Applies per-principal budgets (total calls, per-tool cap, wall-clock).
5. Emits an audit event and a corresponding `AgentStep`.

## Content filters

`src/core/filters.py` detects GCP SA key JSON, PEM private keys, GitHub PATs, AWS access keys, Slack tokens, Google API keys, emails, phones, and common injection phrases. Filters run on tool inputs, discovered resource attributes, and anything crossing into the memory sidecar. They never run on generated HCL (which does not cross a trust boundary).

## Observability (AgentTrace)

`src/core/agent_trace.py` records every step with `correlation_id`, `causation_id`, `parent_step_id`, and rationale. `AgentTrace.load(path).replay()` emits a Markdown session transcript; `to_otel_spans()` produces OTLP-compatible dicts for Cloud Trace export.

## Explainability

Every agent step writes its *rationale* (free-text, short) into the audit log. The optional `rationale_writer` LLM agent (see `adk_bridge.py`) composes a human-readable run summary from the audit trail for the PR/ticket.

## Anomaly detection (today vs. future)

Today:
- Cycle detection on the dependency graph (logged on warn).
- Manual-resource flagging.
- Deny-pattern matching.

Planned:
- Baseline comparison: diff classified output across runs, alert on churn > N%.
- ReasoningBank-style pattern memory of prior good/bad runs (hook via `mcp__claude-flow__hooks_intelligence_pattern-store`).
- Per-domain drift detectors.

## Memory controls (§11.6)

When `memory.enabled: true`, the ReasoningBank agent writes trajectory
summaries (scope / outcome / violations / validation steps) to an AgentDB-
backed sidecar (`sidecar/`). Framework §11.6 applies:

1. **Retention policy.** `settings.memory.retention_days` (default 180) is
   passed to `ReasoningBank.prune(max_age_seconds=...)` by operational cron
   (wire-up is operator-side; see `sidecar/README.md`).
2. **User-scoped deletion.** `ReasoningBank.delete_by_correlation(id)` exists
   but returns an explicit error today — the sidecar `/delete` endpoint is
   an L2 extension. Right-to-be-forgotten requests are satisfied by
   namespace-wide prune until that ships.
3. **Cross-session isolation.** `namespace` defaults to the
   `project.scope_id`, so trajectories from one GCP project cannot be
   retrieved from a namespace for a different project.
4. **Memory-injection defence.** Every payload passes through
   `FilterStack.scan()` before crossing the loopback socket. Secret-class
   findings block the write; PII findings are audited.

Sidecar posture: loopback bind + bearer-token auth + content-filter
pre-check. Not a managed service — see the boundary contract's
`migration_notes` for the L2 shape.

## Compliance checklist

- [x] No secrets in source or config
- [x] WIF preferred; ADC opt-in via `auth.allow_adc`; credential source recorded per run
- [x] Least-privilege IAM on discovery SA
- [x] Sandbox project isolation enforced at runtime (`SandboxLifecycle.__init__`)
- [x] Chained SHA-256 audit log with fsync + signed manifest
- [x] Tool governor as single enforcement point with named allow-list + budgets
- [x] PII + secret + injection filter stack on tool I/O
- [x] Kill-switch (<1 min) via file + env
- [x] HMAC-signed HITL approval tokens with expiry and single-use nonce
- [x] Hermetic terraform subprocess (scoped PATH, env allow-list, plugin cache)
- [x] Every mutation gated by HITL (sandbox apply; prod-apply path not wired yet)
- [x] Timeout on all terraform operations
- [x] Deterministic pipeline (reproducible builds)

Full L1/L2 mapping lives in [`docs/governance/GAP_ANALYSIS.md`](governance/GAP_ANALYSIS.md).
