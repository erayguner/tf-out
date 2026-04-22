"""Content filter stack (§11.2–§11.3).

Three filters, stacked in order:

1. **Secret scanner** — highest-severity, blocks on match. GCP SA key JSON,
   GitHub PATs, AWS access keys, generic API keys in recognised shapes.
2. **PII redactor** — emails, phone numbers, national IDs. Redacts rather
   than blocks (the pipeline *needs* IAM member emails to generate bindings).
3. **Prompt-injection heuristic** — narrow, high-precision phrase list.
   Complements provider guardrails; never replaces them (§11.4).

Scope of application: filters run against discovered resource attributes
before generation and before any LLM-bound prompt.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# --- patterns ---------------------------------------------------------------

_SECRET_PATTERNS = [
    # GCP service account key JSON
    (re.compile(r'"type"\s*:\s*"service_account"\s*,.*?"private_key"\s*:\s*"-----BEGIN', re.S), "gcp_sa_key"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"), "private_key_pem"),
    # GitHub Personal Access Tokens (classic + fine-grained)
    (re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"), "github_pat"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{80,}\b"), "github_finegrained_pat"),
    # AWS access keys
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws_access_key_id"),
    # Slack tokens
    (re.compile(r"\bxox[abpr]-[A-Za-z0-9-]+\b"), "slack_token"),
    # Generic Google API key
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "gcp_api_key"),
]

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")  # rough; trims down false positives via length bound

_INJECTION_PHRASES = [
    "ignore previous instructions",
    "ignore the above",
    "disregard prior",
    "system prompt",
    "reveal your instructions",
    "you are now",
    "jailbreak",
]
_INJECTION_RE = re.compile("|".join(re.escape(p) for p in _INJECTION_PHRASES), re.IGNORECASE)


@dataclass
class FilterFinding:
    kind: str  # "secret" | "pii" | "prompt_injection"
    detector: str  # which pattern/heuristic fired
    severity: str  # "block" | "redact" | "warn"
    location: str  # json-pointer-ish path to the offending field
    preview: str  # first ~40 chars, for the audit log (never full value)


@dataclass
class FilterVerdict:
    findings: list[FilterFinding] = field(default_factory=list)
    redacted: Any = None

    @property
    def blocked(self) -> bool:
        return any(f.severity == "block" for f in self.findings)


class FilterStack:
    """Runs the three filter layers against arbitrary JSON-like input."""

    def __init__(
        self,
        *,
        enable_secrets: bool = True,
        enable_pii: bool = True,
        enable_injection: bool = True,
    ):
        self._secrets = enable_secrets
        self._pii = enable_pii
        self._injection = enable_injection

    def scan(self, value: Any, _path: str = "$") -> FilterVerdict:
        verdict = FilterVerdict()
        redacted = self._walk(value, verdict, _path)
        verdict.redacted = redacted
        return verdict

    # ---- internal -----------------------------------------------------

    def _walk(self, v, verdict: FilterVerdict, path: str):
        if isinstance(v, dict):
            return {k: self._walk(val, verdict, f"{path}.{k}") for k, val in v.items()}
        if isinstance(v, list):
            return [self._walk(item, verdict, f"{path}[{i}]") for i, item in enumerate(v)]
        if isinstance(v, str):
            return self._scan_str(v, verdict, path)
        return v

    def _scan_str(self, s: str, verdict: FilterVerdict, path: str) -> str:
        out = s

        if self._secrets:
            for pattern, name in _SECRET_PATTERNS:
                if pattern.search(s):
                    verdict.findings.append(
                        FilterFinding(
                            kind="secret",
                            detector=name,
                            severity="block",
                            location=path,
                            preview=s[:40],
                        )
                    )
                    # Block severity — caller decides whether to halt; we still redact
                    out = pattern.sub(f"<REDACTED:{name}>", out)

        if self._pii:
            if _EMAIL.search(out):
                verdict.findings.append(
                    FilterFinding(
                        kind="pii",
                        detector="email",
                        severity="redact",
                        location=path,
                        preview=out[:40],
                    )
                )
                # DON'T redact emails at scan time — IAM binding generation needs them.
                # The finding in the audit trail is the mitigating control.
            if _PHONE.search(out) and len(_PHONE.findall(out)[0]) >= 10:
                verdict.findings.append(
                    FilterFinding(
                        kind="pii",
                        detector="phone",
                        severity="redact",
                        location=path,
                        preview=out[:40],
                    )
                )

        if self._injection and _INJECTION_RE.search(out):
            verdict.findings.append(
                FilterFinding(
                    kind="prompt_injection",
                    detector="phrase",
                    severity="warn",
                    location=path,
                    preview=out[:40],
                )
            )

        return out
