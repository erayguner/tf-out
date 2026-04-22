"""Append-only audit log — with tamper evidence (§8.2).

Each entry carries:

* ``seq``       — monotonic sequence within a run
* ``prev_hash`` — SHA-256 of the previous entry's canonical JSON (genesis = 64 zeros)
* ``hash``      — SHA-256 of this entry's canonical JSON (including ``prev_hash``)

Any edit to a past entry invalidates every subsequent ``hash``. ``verify_chain()``
walks the file and raises on the first break — framework §8.2 requires chain
breaks to raise at load time, not silently reset.

On close (``write_manifest``) we emit a signed manifest with the last checksum,
file SHA-256, entry count, and signature. HMAC-SHA256 (dev) is default;
Ed25519 (prod) when an env-provided private key is supplied.

Signed exports (``export_signed``) return a canonical-JSON payload + signature
pair usable as forensic chain-of-custody evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_GENESIS = "0" * 64
_HMAC_ENV = "AI_TF_AUDIT_HMAC_KEY"  # dev signing key
_ED25519_ENV = "AI_TF_AUDIT_ED25519_PEM"  # prod signing key (PEM path)


@dataclass
class AuditEvent:
    timestamp: str
    run_id: str
    seq: int
    actor: str
    action: str
    target: str
    outcome: str
    rationale: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = _GENESIS
    hash: str = ""  # populated by AuditLog before writing


class ChainBroken(RuntimeError):
    """Raised when the audit chain fails verification."""


class AuditLog:
    def __init__(self, log_dir: str | Path, run_id: str | None = None):
        self.run_id = run_id or _generate_run_id()
        self._path = Path(log_dir) / f"{self.run_id}.audit.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch()
        self._seq = 0
        self._last_hash = _GENESIS
        log.info("Audit log opened: %s", self._path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def head_hash(self) -> str:
        return self._last_hash

    # ---- write path ------------------------------------------------------

    def record(
        self,
        actor: str,
        action: str,
        target: str,
        outcome: str,
        rationale: str = "",
        **data: Any,
    ) -> AuditEvent:
        event = AuditEvent(
            timestamp=datetime.now(UTC).isoformat(),
            run_id=self.run_id,
            seq=self._seq,
            actor=actor,
            action=action,
            target=target,
            outcome=outcome,
            rationale=rationale,
            data=data,
            prev_hash=self._last_hash,
        )
        event.hash = _hash_event(event)
        line = json.dumps(asdict(event), separators=(",", ":"), sort_keys=True)

        with self._path.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")
            fp.flush()
            os.fsync(fp.fileno())

        self._seq += 1
        self._last_hash = event.hash
        return event

    # ---- verify / export -------------------------------------------------

    def verify_chain(self) -> int:
        """Re-walk the log. Return entry count. Raise ``ChainBroken`` on tamper."""
        prev = _GENESIS
        count = 0
        with self._path.open(encoding="utf-8") as fp:
            for i, line in enumerate(fp):
                line = line.rstrip()
                if not line:
                    continue
                raw = json.loads(line)
                if raw.get("prev_hash") != prev:
                    raise ChainBroken(f"prev_hash mismatch at entry {i}")
                recomputed = _hash_dict({**raw, "hash": ""})
                if recomputed != raw.get("hash"):
                    raise ChainBroken(f"hash mismatch at entry {i}")
                prev = raw["hash"]
                count += 1
        return count

    def write_manifest(self) -> dict[str, Any]:
        """Produce a signed manifest for the current log file."""
        count = self.verify_chain()
        file_bytes = self._path.read_bytes()
        manifest = {
            "run_id": self.run_id,
            "file": str(self._path),
            "file_sha256": hashlib.sha256(file_bytes).hexdigest(),
            "last_hash": self._last_hash,
            "entry_count": count,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        sig, algo = _sign(json.dumps(manifest, sort_keys=True).encode())
        manifest["signature"] = sig
        manifest["signature_algorithm"] = algo

        manifest_path = self._path.with_suffix(".manifest.json")
        manifest_path.write_text(json.dumps(manifest, indent=2))
        log.info("Audit manifest written: %s (algo=%s)", manifest_path, algo)
        return manifest

    def export_signed(self) -> dict[str, Any]:
        """Return a canonical, signed export bundle for forensic use."""
        count = self.verify_chain()
        payload = {
            "run_id": self.run_id,
            "entries": [json.loads(line) for line in self._path.read_text().splitlines() if line],
            "entry_count": count,
            "head_hash": self._last_hash,
            "exported_at": datetime.now(UTC).isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        sig, algo = _sign(canonical)
        return {"payload": payload, "signature": sig, "algorithm": algo}


# ---- helpers ----------------------------------------------------------------


def _hash_event(event: AuditEvent) -> str:
    d = asdict(event)
    d["hash"] = ""  # exclude from own hash input
    return _hash_dict(d)


def _hash_dict(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sign(payload: bytes) -> tuple[str, str]:
    """Return (signature_hex, algorithm). Prefers Ed25519 if configured."""
    ed_pem = os.getenv(_ED25519_ENV)
    if ed_pem and Path(ed_pem).exists():
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            key = serialization.load_pem_private_key(Path(ed_pem).read_bytes(), password=None)
            if isinstance(key, Ed25519PrivateKey):
                return key.sign(payload).hex(), "ed25519"
        except ImportError:
            log.warning("cryptography not installed; falling back to HMAC")

    hmac_key = os.getenv(_HMAC_ENV, "tf-out-dev-key-not-for-prod").encode()
    return hmac.new(hmac_key, payload, hashlib.sha256).hexdigest(), "hmac-sha256"


def _generate_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"
