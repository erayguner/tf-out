# tf-out agentdb sidecar

Localhost-only AgentDB memory service for the tf-out Python pipeline.

> **Known issue (2026-04):** `server.mjs:19` imports `createAgentDBAdapter`
> from `agentic-flow/reasoningbank`. That export was removed by upstream across
> the full v1.x line and has not returned in v2+. The sidecar will throw on
> startup against any currently-installable version. The Python pipeline
> treats the sidecar as optional (memory defaults to off) and tolerates its
> absence, so the main product is unaffected. Re-enabling memory requires
> adapting `server.mjs` to agentic-flow's current API — tracked separately
> from dependency bumps.

## Security posture

- Binds to `127.0.0.1` only. Loopback-only is not sufficient on multi-tenant hosts — also requires a shared secret (`AI_TF_SIDECAR_TOKEN`) in every request.
- The Python client runs the content filter stack on every payload **before** it reaches the sidecar. Secrets/PII detection stays on the Python side.
- The AgentDB file lives under `.agentdb/` (gitignored). Restrict filesystem permissions to the agent user.

Covered framework controls:
- §7.5 hermetic-ish — single local process, no network egress, auth required
- §11.6 memory controls — retention (`/prune`), user-scoped namespacing, cross-session isolation via `namespace` + `correlation_id`, memory-injection via filter pass on Python side

## Run it

```bash
cd sidecar
npm install
AI_TF_SIDECAR_TOKEN="$(openssl rand -hex 32)" npm start
```

Environment variables:

| Var | Default | Purpose |
|---|---|---|
| `AI_TF_SIDECAR_PORT` | 7443 | Loopback port |
| `AI_TF_SIDECAR_TOKEN` | `dev-token-not-for-prod` | Shared-secret bearer token |
| `AI_TF_SIDECAR_DB` | `.agentdb/tf-out.db` | AgentDB file path |

The Python client must set the same token via `memory.sidecar_token` in `config/settings.yaml` (or the `AI_TF_SIDECAR_TOKEN` env var).

## HTTP contract

All endpoints require `Authorization: Bearer <token>`.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/store` | `{namespace, text, metadata, outcome, correlation_id}` | `{stored}` |
| POST | `/search` | `{namespace, text, k, min_confidence, domain_filter}` | `{patterns[], reasoning}` |
| POST | `/prune` | `{min_confidence, min_usage, max_age_seconds}` | `{pruned, before, after}` |
| GET | `/stats` | — | `{totalPatterns, dbSize, avgConfidence, cacheHitRate}` |
| GET | `/healthz` | — | `{ok, dbPath}` |

## Optimization recipe

Configured for Recipe 2 (balanced) from the agentdb-optimization skill — scalar quantization (4x memory reduction, 98–99% accuracy), HNSW M=16, ef=100, cache 1000. Expected <100µs search latency at <100K patterns.

Scale tuning: change the constants at the top of `server.mjs`.
