# Agent boundary contracts (§3.2)

One YAML per agent, co-located with the agent definition. Every field is load-bearing; incomplete contracts are a finding per §3.2.

Schema — every contract declares:

- `purpose` — one sentence
- `role` — Observer / Advisor / Operator / Autonomous operator (§3.1)
- `owner` + `on_call`
- `in_scope_tools` — allow-list
- `out_of_scope_systems` — explicit negative list
- `delegatable_agents` — A2A allow-list (empty if the agent never delegates)
- `data_classes` — §11.1 classes the agent may encounter
- `approval_class` — per-call / batch / none
- `model_card` — foundation model card URL (§3.2 — contract incomplete without one)

Promotion between roles is a change-management event (§16), not a runtime flag. Edits land via PR with the approvals specified in §16.2.
