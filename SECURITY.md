# Security Policy

## Supported versions

`ai-tf` is pre-1.0. Only the `main` branch receives security fixes.

| Version   | Supported          |
| --------- | ------------------ |
| `main`    | :white_check_mark: |
| `< 0.1.0` | :x:                |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Report privately via one of these channels:

1. **GitHub Private Vulnerability Reporting (preferred).**
   Open a report at <https://github.com/erayguner/tf-out/security/advisories/new>.
   This creates a private advisory visible only to repo maintainers.
2. **Email:** `eray4793@gmail.com` — subject line `ai-tf security report`.
   PGP is available on request.

Please include:

- A description of the issue and the impact you believe it has.
- Steps to reproduce (proof-of-concept, minimal repro, or a link to a branch).
- The commit SHA or release tag you tested against.
- Any logs, stack traces, or screenshots that help.
- Whether you've disclosed the issue to anyone else.

## What to expect

| Stage                                              | Target time  |
| -------------------------------------------------- | ------------ |
| Acknowledgement of your report                     | 48 hours     |
| Initial triage + severity assessment (CVSS v3.1)   | 5 days       |
| Fix, mitigation plan, or request for more info     | 14 days      |
| Coordinated public disclosure after fix is shipped | up to 90 days |

If the 90-day window needs to slip, I'll tell you why and agree a new date with you.

## Scope

In scope:

- Code in `src/`, `sidecar/`, `scripts/`, `config/`, and `.github/workflows/`.
- Supply-chain issues (dependencies declared in `pyproject.toml`, `sidecar/package.json`, `.pre-commit-config.yaml`, `.github/workflows/*`).
- Any material that leaks secrets, bypasses the HITL gate, escapes the sandbox, or tampers with the audit log's hash chain.

Out of scope (please don't report these as vulnerabilities):

- Bugs that require an attacker to already have `roles/owner` on the target GCP project.
- Rate-limit-like behaviour in Cloud Asset Inventory or Terraform itself.
- Vulnerabilities in user-supplied `config/settings.yaml` values (e.g. pointing the tool at an attacker-controlled project).
- Issues in third-party services (Google Cloud, GitHub Actions infrastructure, etc.) — please report those upstream.

## Safe-harbour

Good-faith security research that:

- stays within the scope above,
- avoids privacy violations, service degradation, or data destruction,
- uses only test projects you own (never third-party GCP tenants), and
- gives us a reasonable window to fix before public disclosure,

will not be pursued under CFAA-equivalent theories or DMCA. I will publicly acknowledge reporters who want credit once the issue is fixed.

## Hall of fame

Reporters who have helped improve `ai-tf` will be listed here once the first advisory is resolved.
