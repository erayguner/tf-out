# Gap analysis — ai-tf vs AGENT_GOVERNANCE_FRAMEWORK.md

Review against §19 Minimum compliance checklist. Scope: this MVP aims for **L1 — Foundational** conformance, with named migration paths to L2.

Legend: **MET** / **MITIGATED** (delta implemented in this pass) / **DEFERRED** (L2+ milestone, tracked).

## Identity and access (§7)

| Check | Status | Note |
|---|---|---|
| No static keys | MET | WIF preferred, ADC permitted with audit — `src/auth/credentials.py` |
| IAM ⊆ boundary contract | MITIGATED | Boundary contracts added under `docs/boundaries/` |
| Tool allow-list ⊆ IAM | MITIGATED | Tool governor enforces named allow-list — `src/core/tool_governor.py` |

**ADC decision.** ADC is allowed (user directive) but the credential provider records *which* source was used in the audit log and refuses ADC in production unless `auth.allow_adc: true` is explicitly set in settings. Rationale: ADC opens a broader blast radius (may pick up developer user credentials) than WIF-impersonation — the audit record is the mitigating control.

## Governor (§4)

| Check | Status | Note |
|---|---|---|
| Single enforcement point | MITIGATED | `governed_call` in `src/core/tool_governor.py` — every tool invocation passes through it |
| `default_allow=False` in prod | MITIGATED | `GovernancePolicy(default_allow=False)`; dev can flip via env flag which is audited |
| Schema-validated policy | MET | Pydantic models in `src/settings.py` |
| Per-principal budgets | MITIGATED | `BudgetLimits` in `GovernancePolicy` — total calls, per-tool cap, wall-clock |

## Provider controls (§11.4)

| Check | Status | Note |
|---|---|---|
| Bedrock Guardrails populated | N/A | No Bedrock use |
| Model Armor on Vertex endpoints | DEFERRED | Only `rationale_writer` LLM agent exists (optional). Wiring tracked for L2. |
| Gemini `safety_settings` explicit | MITIGATED | `src/agents/adk_bridge.py` sets HarmCategory thresholds explicitly |
| Data-Access logs enabled | DEFERRED | Terraform config, not code — documented in `docs/runbook.md` |
| Per-agent identity | DEFERRED | Single impersonated SA today. Documented migration to Vertex Agent Identity at L2. |
| Managed threat detection | DEFERRED | Required at L2. Agent Engine Threat Detection once we migrate to managed runtime. |

## Evaluation (§16.3)

| Check | Status | Note |
|---|---|---|
| Regression eval harness | DEFERRED | Placeholder `scripts/eval.sh` stub. Full harness is an L2 item. |

## Memory and sessions (§11.6)

Not applicable — the pipeline is stateless per run. No session memory.

## Data lineage and DLP (§11.7–§11.8)

| Check | Status | Note |
|---|---|---|
| Retrieval sources versioned | MET | CAI scope captured in audit + discovery report |
| Templates in git | MET | Jinja HCL templates under `src/generation/templates/` |
| DLP / Macie | MITIGATED | Filter stack applies PII + secret scanning to tool inputs/outputs — `src/core/filters.py` |

**DLP decision.** Full Sensitive Data Protection integration is deferred; the local pattern-based filter covers the highest-risk surfaces (IAM member emails, accidentally-leaked SA key material). Documented for L2 upgrade.

## Supply chain (§12.3)

| Check | Status | Note |
|---|---|---|
| SLSA ≥ L2 | DEFERRED | Container build not yet — runbook documents SLSA provenance requirement |
| Signed images | DEFERRED | Same |
| MCP server pinned hash | MET | No third-party MCP server consumed |

## Third-party access (§7.2)

| Check | Status | Note |
|---|---|---|
| OAuth/Secret-Manager/OIDC only | MET | Only Google APIs via WIF/ADC |
| User+agent both logged | MET | Audit records both `actor` and WIF/ADC source |

## Fairness (§10.5)

Not applicable — the agent allocates nothing across people/teams.

## Red-teaming (§12.7)

| Check | Status | Note |
|---|---|---|
| Coverage spans injection / escalation / exfil | DEFERRED | Required at L2 for Operator roles |
| Novel findings → regression | DEFERRED | Same |

## Code execution (§7.5)

| Check | Status | Note |
|---|---|---|
| Provider-managed sandbox | MITIGATED | Terraform runs under a **hermetic subprocess** — minimal PATH, no inherited secrets, explicit env allow-list, dedicated plugin cache — see `src/validation/sandbox.py`. Migration to Cloud Build execution is the L2 target. |

Rationale for deviation from "named provider-managed sandbox": there is no Google-managed sandbox for arbitrary `terraform apply` against a customer project. Closest fit (Cloud Build with a terraform image) is documented as the L2 upgrade path.

## Model documentation (§3.2)

| Check | Status | Note |
|---|---|---|
| Model card in boundary contract | MITIGATED | Boundary contracts cite `gemini-2.5-pro` model card URL |
| Adapter version if tuned | N/A | No tuning |

## Approvals (§5)

| Check | Status | Note |
|---|---|---|
| Out-of-band gateway | MITIGATED | HITL gate accepts **HMAC-signed decision tokens** with expiry; CLI / env / webhook channels supported |
| RoC for destructive | MITIGATED | Sandbox apply + policy override + production-apply all pass HITL |
| Pool ≥ 2 for irreversibles | DEFERRED | Quorum is an L2 item — current HITL records a single approver |
| Approvals expire | MITIGATED | Tokens carry `exp`; expired tokens deny |

## Audit (§8)

| Check | Status | Note |
|---|---|---|
| Chained checksum | MITIGATED | Each line carries `prev_hash` + `hash` (SHA-256); chain verification at load time — `AuditLog.verify_chain()` |
| Daily signed manifest | MITIGATED | `AuditLog.write_manifest()` emits an HMAC-SHA256 (dev) / Ed25519 (prod key provided) signed manifest |
| `export_signed` | MITIGATED | `AuditLog.export_signed()` returns `(payload, signature, algorithm)` |
| Independent storage | DEFERRED | Runbook documents shipping to a separate-project Cloud Logging sink with deny-delete IAM |

## Observability (§9)

| Check | Status | Note |
|---|---|---|
| Per-session AgentTrace | MITIGATED | `src/core/agent_trace.py` — AgentTrace + AgentStep with `correlation_id` / `causation_id` / `parent_step_id` |
| Rationale on every step | MET | Audit events carry `rationale`; AgentStep does too |
| Anomaly detectors | DEFERRED | Call-rate + tool-distribution detectors are an L2 item |
| Replay tool | MITIGATED | `AgentTrace.replay()` reconstructs a session from the trace store |
| OTel emission | MITIGATED | Trace model exposes `to_otel_spans()` producing OTLP-compatible dicts; exporter wiring is a config step |

## Content filters (§11.2–§11.3)

| Check | Status | Note |
|---|---|---|
| PII redactor | MITIGATED | `src/core/filters.py` — emails, phones, keys |
| Secret scanner | MITIGATED | GCP SA key JSON, GitHub token, AWS access key patterns — blocks on match |
| Prompt-injection heuristic | MITIGATED | Narrow pattern set; complements (never replaces) provider filters |

Scope of application: filters run against **discovered resource attributes** before generation and before any LLM call. They do NOT run on HCL output, which by construction never crosses a trust boundary.

## Human oversight (§14)

| Check | Status | Note |
|---|---|---|
| Kill-switch <1 min | MITIGATED | `src/governance/kill_switch.py` — file-based denylist the governor consults; also `AI_TF_HALT=<run_id>` env |
| Override API emits HumanOverrideStep | MITIGATED | HITL decisions are now explicit `HumanOverrideStep`s in the trace |
| Alerts contextualised | MET | Audit events name actor/action/target/rationale |

## Change management (§16)

| Check | Status | Note |
|---|---|---|
| Policies/prompts/contracts in git | MET | Everything under `config/` and `docs/boundaries/` |
| Pre-flight CI gates | DEFERRED | CI workflow shipped as `scripts/preflight.sh` skeleton; wiring into GitHub Actions is an L2 step |
| Staged rollout | DEFERRED | Not applicable until agent is deployed |
| Deprecation window | MET | README commits to one-release deprecation for breaking defaults |

## Incident response (§15)

| Check | Status | Note |
|---|---|---|
| Runbook per incident class | MITIGATED | `docs/runbook.md` extended with agent-specific incidents (kill-switch, chain break, unauthorised action) |
| Forensic export | MITIGATED | `AuditLog.export_signed()` produces a bundle usable as chain-of-custody |
| Quarterly DR exercise | DEFERRED | Operational cadence, not code |

---

## Summary

**L1 Foundational conformance: achieved after this pass.**

Residual L2 items are tracked with explicit migration paths:

1. **Per-agent Vertex Agent Identity** (replacing shared impersonated SA)
2. **Managed runtime** (Vertex Agent Engine Runtime) replacing local Python host
3. **Managed threat detection** (SCC Agent Engine Threat Detection)
4. **Regression eval harness** on the six named dimensions
5. **Quorum (2-of-N) approvals** for irreversibles
6. **Independent-blast-radius audit storage** (separate-project Cloud Logging sink with WORM)
7. **Cloud Build terraform runner** (in place of local subprocess)
8. **OTel exporter wiring** to Cloud Trace
9. **DLP API** replacing local pattern-based filters for regulated data
10. **Anomaly detectors** (call-rate, tool-distribution, cost)
