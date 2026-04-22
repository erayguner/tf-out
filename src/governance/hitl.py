"""Human-in-the-loop approval gate (§5, §14.2).

Out-of-band approval with **HMAC-signed decision tokens** and **expiry**.
Tokens are the primitive the framework prescribes (§5.2); the same token
shape is consumable by CLI, webhook, or chat channels.

Token shape (base64url-compact):

    <payload_b64>.<signature_b64>
    payload = {"run": <run_id>, "action": <action>, "decision": <granted|denied>,
               "approver": <principal>, "reason": <text>, "exp": <epoch_s>}

The signature is HMAC-SHA256 over the payload bytes using ``AI_TF_HITL_KEY``
(dev) or a provider KMS key (prod, via a pluggable signer).

Expired tokens are denied and audited. Tokens are single-use by session
scope — once accepted for a request, the approver cannot re-use the same
token for a different action in the same run.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass

log = logging.getLogger(__name__)

_SIGNING_ENV = "AI_TF_HITL_KEY"
_DEFAULT_TTL_SECONDS = 900  # 15 minutes per-action (framework §5.4)


@dataclass
class Approval:
    granted: bool
    approver: str
    reason: str
    channel: str  # cli | env | token
    expires_at: int = 0
    nonce: str = ""  # token signature tail — de-dup key


class ApprovalExpired(RuntimeError):
    pass


class ApprovalForged(RuntimeError):
    pass


class HumanGate:
    ENV_TOKEN = "AI_TF_APPROVAL_TOKEN"  # preferred OOB channel
    ENV_APPROVE = "AI_TF_APPROVE"  # simple CI short-circuit
    ENV_APPROVER = "AI_TF_APPROVER"
    ENV_REASON = "AI_TF_APPROVAL_REASON"

    def __init__(
        self,
        interactive: bool | None = None,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        approver_pool: Iterable[str] | None = None,
    ):
        self._interactive = sys.stdin.isatty() if interactive is None else interactive
        self._ttl = ttl_seconds
        self._pool = set(approver_pool or [])
        self._consumed_nonces: set[str] = set()

    # ---- core request path --------------------------------------------

    def request(self, action: str, summary: str, run_id: str = "") -> Approval:
        # 1) Signed token (preferred, OOB)
        token = os.getenv(self.ENV_TOKEN, "").strip()
        if token:
            return self._verify_token(action, run_id, token)

        # 2) Interactive TTY
        if self._interactive:
            return self._prompt_tty(action, summary)

        # 3) Non-interactive env short-circuit (CI pre-approved)
        return self._env_approval(action)

    # ---- helpers -------------------------------------------------------

    def _verify_token(self, action: str, run_id: str, token: str) -> Approval:
        try:
            payload_b64, sig_b64 = token.split(".", 1)
            payload_bytes = _b64d(payload_b64)
            sig_bytes = _b64d(sig_b64)
        except Exception as exc:
            raise ApprovalForged(f"malformed token: {exc}") from exc

        expected = hmac.new(_signing_key(), payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, sig_bytes):
            raise ApprovalForged("signature mismatch")

        payload = json.loads(payload_bytes)
        if payload.get("action") != action:
            raise ApprovalForged(f"token action mismatch: {payload.get('action')!r} != {action!r}")
        if run_id and payload.get("run") not in ("*", run_id):
            raise ApprovalForged("token scoped to a different run_id")
        if payload.get("exp", 0) < int(time.time()):
            raise ApprovalExpired(f"token expired at {payload.get('exp')}")
        if self._pool and payload.get("approver") not in self._pool:
            raise ApprovalForged(f"approver {payload.get('approver')!r} not in pool")

        nonce = sig_b64[-16:]
        if nonce in self._consumed_nonces:
            raise ApprovalForged("token already consumed")
        self._consumed_nonces.add(nonce)

        return Approval(
            granted=bool(payload.get("decision") == "granted"),
            approver=str(payload.get("approver", "unknown")),
            reason=str(payload.get("reason", "")),
            channel="token",
            expires_at=int(payload.get("exp", 0)),
            nonce=nonce,
        )

    def _prompt_tty(self, action: str, summary: str) -> Approval:
        print(f"\n[HITL] Action requires approval: {action}", file=sys.stderr)
        print(summary, file=sys.stderr)
        answer = input("Approve? [y/N]: ").strip().lower()
        reason = input("Reason/ticket: ").strip() or "no-reason-given"
        return Approval(
            granted=answer in {"y", "yes"},
            approver=os.getenv("USER", "local"),
            reason=reason,
            channel="cli",
            expires_at=int(time.time()) + self._ttl,
        )

    def _env_approval(self, action: str) -> Approval:
        granted = os.getenv(self.ENV_APPROVE, "").strip().lower() in {"yes", "y", "true", "1"}
        approver = os.getenv(self.ENV_APPROVER, "ci")
        reason = os.getenv(self.ENV_REASON, "ci-preapproved")
        if self._pool and approver not in self._pool:
            return Approval(
                granted=False,
                approver=approver,
                reason=f"approver {approver} not in pool",
                channel="env",
                expires_at=0,
            )
        log.info("HITL env approval action=%s granted=%s approver=%s", action, granted, approver)
        return Approval(
            granted=granted,
            approver=approver,
            reason=reason,
            channel="env",
            expires_at=int(time.time()) + self._ttl,
        )


# ---- token minting (operator-side helper) ----------------------------------


def mint_token(
    run_id: str,
    action: str,
    decision: str,
    approver: str,
    reason: str = "",
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> str:
    """Mint an approval token. Intended for operator CLIs or chat bots."""
    if decision not in {"granted", "denied"}:
        raise ValueError(f"invalid decision: {decision}")
    payload = {
        "run": run_id,
        "action": action,
        "decision": decision,
        "approver": approver,
        "reason": reason,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(_signing_key(), payload_bytes, hashlib.sha256).digest()
    return f"{_b64e(payload_bytes)}.{_b64e(sig)}"


def _signing_key() -> bytes:
    key = os.getenv(_SIGNING_ENV)
    if not key:
        log.warning("%s unset — using insecure default signing key (dev only)", _SIGNING_ENV)
        key = "tf-out-dev-hitl-key-not-for-prod"
    return key.encode()


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)
