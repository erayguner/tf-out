"""Classification Agent — labels each discovered resource as TF-supported / importable / manual."""

from __future__ import annotations

import logging

from ..discovery.classifiers import classify_all
from ..settings import Settings

log = logging.getLogger(__name__)


class ClassificationAgent:
    name = "classification"

    def __init__(self, settings: Settings):
        self._s = settings

    def run(self, ctx):
        if not ctx.discovery:
            raise RuntimeError("discovery step did not populate context")
        ctx.classified = classify_all(ctx.discovery.resources)

        counts: dict[str, int] = {}
        for c in ctx.classified:
            counts[c.status] = counts.get(c.status, 0) + 1

        ctx.audit.record(
            self.name,
            "classified",
            ctx.discovery.scope,
            "success",
            rationale=f"counts={counts}",
            counts=counts,
        )
        return ctx
