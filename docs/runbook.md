# Operational runbook

## Terminology (read first)

The word *agent* appears in three unrelated senses in this codebase. Keep them straight:

| Sense | What it is | Where it lives |
|---|---|---|
| **Pipeline agent** | A Python class implementing `run(ctx) -> ctx`. One per pipeline stage (discovery, classification, governance, generation, dependency, validation, reasoning_bank). | `src/agents/*.py` |
| **GCP agent SA** | The Google Cloud service account `ai-tf-agent@…` that the pipeline impersonates at runtime. | IAM, see "WIF setup" below |
| **Agent trace** | Per-run replayable log of what the pipeline did. | `traces/<run_id>.trace.jsonl`, see "Investigating" below |

When the runbook says "agent runtime" it means *the process that executes the pipeline* — not a separate agent daemon. There is no deploy step for agents themselves; see "Deploying agents" below.

## Deploying agents

"Deploying agents" = running the pipeline. Pipeline agents are plain Python classes wired by `src/agents/orchestrator.py::build_pipeline` in a fixed order:

```
DiscoveryAgent → ClassificationAgent → (hydrate_prior_runs) → GovernanceAgent
→ TerraformAgent → DependencyAgent → ValidationAgent → ReasoningBankAgent
```

Two entry points are supported:

1. **Deterministic Python runner** — default, no LLM in the loop:
   ```bash
   uv run ai-tf run --config config/settings.yaml
   ```
   Each stage runs in sequence, writes to `PipelineContext`, and records its actions in the audit log. This is what CI uses.

2. **Google ADK runner** (optional, experimental) — wraps the same pipeline as a single ADK `FunctionTool` under a `gemini-2.5-pro` `LlmAgent` whose only job is to call the tool and narrate the result. Use this when you want a natural-language summary of a run.
   ```python
   from src.agents.adk_bridge import build_adk_root
   from src.settings import load
   from google.adk.runners import Runner
   from google.adk.sessions import InMemorySessionService

   root = build_adk_root(load("config/settings.yaml"))
   runner = Runner(agent=root, app_name="tf-out", session_service=InMemorySessionService())
   # then drive `runner` per ADK docs
   ```
   `google-adk` is already in base deps (installed by `uv sync`). There is deliberately **no CLI command** for this path — the ADK runner API is too flexible to lock into a flag. Drive it from your own script.

Adding a new pipeline agent:

1. Create `src/agents/<name>_agent.py` exposing `class XAgent: def run(self, ctx) -> ctx`.
2. Insert it into `build_pipeline` at the correct position (dependencies flow left-to-right via `PipelineContext`).
3. Add a boundary contract at `docs/boundaries/<name>_agent.yaml`.
4. Add tests under `tests/test_<name>.py`.

## One-time: WIF setup

The agent runtime must be able to exchange a runtime-issued OIDC/JWT token (GitHub OIDC, GKE K8s SA, Cloud Run identity) for a short-lived Google access token impersonating a scoped service account.

1. **Create the agent service account** in the host project:
   ```bash
   gcloud iam service-accounts create ai-tf-agent --project=$HOST_PROJECT
   ```

2. **Grant least-privilege discovery roles** on the target scope (project/folder/org):
   ```bash
   for R in roles/cloudasset.viewer roles/iam.securityReviewer roles/compute.viewer; do
     gcloud projects add-iam-policy-binding $TARGET_PROJECT \
       --member="serviceAccount:ai-tf-agent@$HOST_PROJECT.iam.gserviceaccount.com" \
       --role="$R"
   done
   ```

3. **Grant sandbox write roles** on the sandbox project only:
   ```bash
   gcloud projects add-iam-policy-binding $SANDBOX_PROJECT \
     --member="serviceAccount:ai-tf-agent@$HOST_PROJECT.iam.gserviceaccount.com" \
     --role="roles/owner"    # scope-limited to sandbox; never used on target
   ```

4. **Create the Workload Identity Pool + Provider** (GitHub OIDC example):
   ```bash
   gcloud iam workload-identity-pools create ai-tf-pool --location=global
   gcloud iam workload-identity-pools providers create-oidc ai-tf-github \
     --location=global --workload-identity-pool=ai-tf-pool \
     --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
     --issuer-uri="https://token.actions.githubusercontent.com"
   ```

5. **Bind the federated principal to the SA**:
   ```bash
   gcloud iam service-accounts add-iam-policy-binding \
     ai-tf-agent@$HOST_PROJECT.iam.gserviceaccount.com \
     --role=roles/iam.workloadIdentityUser \
     --member="principalSet://iam.googleapis.com/projects/$HOST_PROJECT_NUMBER/locations/global/workloadIdentityPools/ai-tf-pool/attribute.repository/$ORG/$REPO"
   ```

6. **Fill `config/wif_config.json`** using `config/wif_config.example.json` as a template.

## Running the pipeline

### Local dev (ADC — fastest path)

For local exploration, use `gcloud`'s Application Default Credentials. ai-tf refuses ADC by default; flip the opt-in explicitly:

```bash
uv sync                                                      # creates .venv, installs from uv.lock
gcloud auth application-default login

# Opt in — keep this change local; settings.yaml is committed.
$EDITOR config/settings.yaml        # set auth.allow_adc: true

uv run ai-tf inspect                                         # sanity-check settings
uv run ai-tf run --config config/settings.yaml               # interactive HITL on stdin
```

`uv run <cmd>` runs inside the project venv without activation. To activate manually: `source .venv/bin/activate` after `uv sync`.

Two safety notes:
- Revert `allow_adc: false` before committing. The flag exists so CI can't accidentally fall back to a developer's user credential.
- `validation.sandbox_project_id` must point at a dedicated empty project for validation to run. Leave it empty to let the pipeline finish after generation — the validate stage will refuse with a clear message.

### Day-to-day uv commands

```bash
uv sync                      # install / refresh the venv from uv.lock
uv sync --upgrade            # bump locked versions within the floors in pyproject.toml
uv add <pkg>                 # add a runtime dep (writes pyproject.toml + uv.lock)
uv add --dev <pkg>           # add a dev dep
uv remove <pkg>              # remove
uv run pytest -q             # run tests
uv run ruff check src tests  # lint
uv lock --upgrade-package <pkg>   # bump just one package
```

### CI (GitHub Actions)
```yaml
- uses: astral-sh/setup-uv@v5             # installs uv and caches ~/.cache/uv
  with:
    enable-cache: true
- run: uv sync --frozen                   # install from uv.lock (no resolver runs)
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: projects/.../providers/tf-out-github
    service_account: tf-out-agent@$HOST_PROJECT.iam.gserviceaccount.com
    create_credentials_file: true
- env:
    AI_TF_APPROVE: "yes"
    AI_TF_APPROVER: ${{ github.actor }}
    AI_TF_APPROVAL_REASON: "pr-${{ github.event.pull_request.number }}"
    AI_TF_HITL_KEY: ${{ secrets.AI_TF_HITL_KEY }}     # HMAC key for signed approvals
  run: ./scripts/run_pipeline.sh
```

`uv sync --frozen` fails the build if `uv.lock` is out of sync with `pyproject.toml` — guarantees CI installs exactly what was reviewed on the PR.

The runner resolves credentials via `src/auth/credentials.py`: WIF if `wif_config_path` is set, ADC if `auth.allow_adc: true`, otherwise it refuses to start. Every run records which source was used.

## Sandbox lifecycle guarantees

- `SandboxLifecycle` refuses to run if the sandbox project sits inside the discovery scope.
- `terraform destroy` always runs, even when `apply` fails — see the `try/finally` in `src/validation/sandbox.py`.
- `validation.apply_timeout_seconds` caps every terraform operation.
- Terraform runs hermetic: scoped PATH, env allow-list, per-run plugin cache. No inherited secrets.
- When `GENERATE_CONFIG.md` is present, the stage runs `plan -generate-config-out=auto_generated.tf` before the regular plan, materialising HCL for import-only resources.

## Halting a run (<1 minute)

Two channels. The governor consults both before every tool call.

```bash
# Filesystem — works across hosts when kill_dir is a shared volume
echo '{"reason":"operator halt: unexpected scope"}' > kill/<run_id>.halt

# Environment — single-host dev
AI_TF_HALT=<run_id> AI_TF_HALT_REASON="pager" uv run ai-tf run
# Use AI_TF_HALT=* to halt every run in the process
```

Clear the halt by deleting the file. The halt itself is audited on first observation.

## Approving out of band (HMAC tokens)

HITL accepts signed approval tokens. Mint one from an operator shell or chat bot:

```bash
export AI_TF_HITL_KEY="$(openssl rand -hex 32)"   # same key as the runner
python -c "from src.governance.hitl import mint_token; \
  print(mint_token(run_id='20260421T120000Z-abcd', action='sandbox_apply', \
                   decision='granted', approver='eray', reason='ticket-123', ttl_seconds=900))"
```

Pass the token back via `AI_TF_APPROVAL_TOKEN`. Expired, reused, or cross-action tokens deny automatically.

## Investigating a failed run

1. Open `audit-logs/<run_id>.audit.jsonl`. Each line is `{timestamp, actor, action, target, outcome, rationale, prev_hash, hash}`.
2. Filter failures and denials:
   ```bash
   jq -c 'select(.outcome | IN("failure","denied"))' audit-logs/<run_id>.audit.jsonl
   ```
3. Verify the chain is intact:
   ```bash
   python -c "from src.governance.audit import AuditLog; \
     print(AuditLog('audit-logs', run_id='<run_id>').verify_chain(), 'entries OK')"
   ```
   A `ChainBroken` exception means the file was tampered with. Read the signed manifest at `audit-logs/<run_id>.audit.manifest.json` (written at run end) against an out-of-band copy for chain-of-custody.
4. For terraform failures, `stdout`/`stderr` stay out of the audit log. Re-run the failed sub-command from `generated-terraform/` with `TF_LOG=DEBUG`.
5. Replay the agent trace as Markdown:
   ```bash
   python -c "from src.core.agent_trace import AgentTrace; \
     print(AgentTrace.load('traces/<run_id>.trace.jsonl').replay())"
   ```

## Memory sidecar (optional)

The pipeline runs fine without memory. Enable it for pattern learning over
past runs. Loopback-only, bearer-token auth, fail-open from the Python side.

```bash
cd sidecar
npm install
export AI_TF_SIDECAR_TOKEN="$(openssl rand -hex 32)"
npm start &
```

Then enable in `config/settings.yaml`:

```yaml
memory:
  enabled: true
  sidecar_url: http://127.0.0.1:7443
  # sidecar_token read from AI_TF_SIDECAR_TOKEN env var if unset here
```

Verify:

```bash
curl -H "authorization: bearer $AI_TF_SIDECAR_TOKEN" \
  http://127.0.0.1:7443/healthz
# → {"ok":true,"dbPath":".agentdb/tf-out.db"}
```

Maintenance:

```bash
# Retention — prune trajectories older than 180 days and below confidence 0.3
curl -sXPOST -H "authorization: bearer $AI_TF_SIDECAR_TOKEN" \
  -H "content-type: application/json" \
  -d '{"min_confidence":0.3,"max_age_seconds":15552000}' \
  http://127.0.0.1:7443/prune
```

See `docs/boundaries/reasoning_bank_agent.yaml` for the full control surface.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `WifConfigError: Expected 'external_account'` | Wrong key in wif_config.json | Regenerate from `gcloud iam workload-identity-pools create-cred-config` |
| `SandboxViolation: sandbox project inside discovery scope` | Misconfig | Use a dedicated empty project |
| `Policy denied: N blocking violations` | e.g. `allUsers` binding in live env | Fix the binding OR waive via HITL with a ticket in the reason |
| `terraform: Error 403` on apply | SA lacks roles on sandbox | Grant `roles/owner` on sandbox project only |
| `MANUAL_RESOURCES.md` listed | asset_type unmapped | Add to `REGISTRY` in classifiers.py or write HCL by hand |
| `ImportError: google-adk is not installed` from `build_adk_root` | Optional ADK runtime not available | Run `uv sync` (google-adk is in base deps) — or stay on the Python runner |
| Agent trace empty / missing | Run didn't reach `ReasoningBankAgent` (tail stage) | Check `audit-logs/<run_id>.audit.jsonl` for the first failed step |
