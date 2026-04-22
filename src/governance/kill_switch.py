"""Kill-switch (§14.1).

Operator halts a session in < 1 minute without killing the process. The
governor consults ``is_halted()`` before every tool call; a halted session
receives ``ToolDecision.HALT`` and short-circuits with ``halt_reason``.

Two halt channels are supported:

1. **Filesystem denylist** — write a JSON file at ``<kill_dir>/<run_id>.halt``
   (or ``<kill_dir>/*.halt``) with ``{"reason": "..."}``. Works across hosts
   when the path is a shared volume.
2. **Environment variable** — ``AI_TF_HALT=<run_id>`` (or ``*``) short-circuits
   the current process. Convenient in single-host dev.

A halt is itself audited when first observed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_HALT_ENV = "AI_TF_HALT"
_HALT_REASON_ENV = "AI_TF_HALT_REASON"


@dataclass
class KillSwitch:
    run_id: str
    halt_dir: Path

    def __post_init__(self) -> None:
        self.halt_dir = Path(self.halt_dir)
        self.halt_dir.mkdir(parents=True, exist_ok=True)
        self._halted = False  # sticky once observed

    def check(self) -> tuple[bool, str]:
        if self._halted:
            return True, "previously halted"

        env_target = os.getenv(_HALT_ENV, "").strip()
        if env_target and env_target in {self.run_id, "*"}:
            self._halted = True
            return True, os.getenv(_HALT_REASON_ENV, "env halt")

        run_file = self.halt_dir / f"{self.run_id}.halt"
        wildcard = self.halt_dir / "all.halt"
        for path in (run_file, wildcard):
            if path.exists():
                self._halted = True
                try:
                    reason = json.loads(path.read_text()).get("reason", "file halt")
                except Exception:
                    reason = "file halt (unparseable body)"
                return True, reason

        return False, ""

    # Operator-facing helpers ---------------------------------------------

    def halt(self, reason: str) -> Path:
        """Write the halt file. Intended for operator CLIs, not agent code."""
        p = self.halt_dir / f"{self.run_id}.halt"
        p.write_text(json.dumps({"reason": reason}))
        log.warning("KillSwitch armed for run=%s: %s", self.run_id, reason)
        return p

    def clear(self) -> None:
        p = self.halt_dir / f"{self.run_id}.halt"
        if p.exists():
            p.unlink()
        self._halted = False
