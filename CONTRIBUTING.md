# Contributing to tf-out

Thanks for your interest in contributing. This document is short on purpose — most questions are answered by the code and by the docs in `docs/`.

## Ways to contribute

- **Report bugs or request features** — open an issue using the provided templates.
- **Improve resource coverage** — follow the "Extending coverage" section in the `README.md`. A PR that adds one asset type (registry row + template) is a great first contribution.
- **Harden governance** — add tests to `tests/test_filters.py` or `tests/test_governance.py` for missed secret/PII patterns.
- **Documentation** — fixes to `README.md`, `docs/runbook.md`, `docs/architecture.md`, and `docs/governance.md` are always welcome.

## Development setup

```bash
uv sync                      # create .venv, install pinned deps from uv.lock
uv run pytest                # run the test suite (no network)
uv run tf-out inspect         # sanity-check settings
```

No live GCP access is required to develop or test. Tests are hermetic.

## Pull request checklist

Before opening a PR:

1. `uv run pytest` passes locally.
2. New behaviour has tests (`tests/test_*.py`).
3. No secrets, credentials, or real project IDs in the diff. Use `projects/YOUR_PROJECT_ID` or `example-project-12345` as placeholders.
4. Commit messages are descriptive; prefer [Conventional Commits](https://www.conventionalcommits.org/) style (`feat:`, `fix:`, `docs:`).
5. If you touched `src/generation/templates/` or `src/discovery/classifiers.py`, update `docs/RESOURCE_COVERAGE.md`.
6. If you touched anything in `src/governance/` or `src/core/filters.py`, update `docs/governance.md` and flag the change in the PR description for review.

## Code style

- Python ≥ 3.13, typed function signatures for public APIs.
- Keep files under ~500 lines; prefer small, focused modules.
- No silent fallbacks — either handle the error or let it surface.
- Tests follow London-school mocking where external collaborators exist (CAI client, terraform subprocess, sidecar).

## Security-sensitive changes

Anything touching `src/core/filters.py`, `src/governance/`, `src/auth/`, or the sidecar needs an extra reviewer and a note in the PR description describing the threat-model impact. See `SECURITY.md` for the private-disclosure channel.

## Code of Conduct

This project adopts the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md). Reports to the address listed there.
