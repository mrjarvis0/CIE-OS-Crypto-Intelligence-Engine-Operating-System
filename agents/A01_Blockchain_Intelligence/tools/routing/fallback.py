"""
Tools :: Routing :: Fallback
============================

Handles routing failures: alternative tools, models, RPCs and adapters,
retry chains and human escalation. Failures never terminate a workflow
without evaluation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..utils.helpers import elapsed_ms, iso_now

__all__ = ["FallbackResult", "FallbackChain"]


@dataclass
class FallbackResult:
    """Outcome of evaluating a fallback chain."""

    ok: bool
    target_id: str = ""
    attempts: int = 0
    detail: str = ""
    escalated: bool = False
    duration_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "target_id": self.target_id,
            "attempts": self.attempts,
            "detail": self.detail,
            "escalated": self.escalated,
            "duration_ms": round(self.duration_ms, 3),
        }


class FallbackChain:
    """Evaluates alternatives in order until one succeeds."""

    def __init__(self, alternatives: Optional[Sequence[Mapping[str, Any]]] = None) -> None:
        self.alternatives = list(alternatives or [])

    def add(self, target: Mapping[str, Any]) -> None:
        self.alternatives.append(dict(target))

    def execute(
        self,
        fn: Callable[[Mapping[str, Any]], Any],
        *,
        retries: int = 0,
        escalate_on_failure: bool = True,
    ) -> FallbackResult:
        """Run ``fn`` against each alternative (with per-target retries)."""
        started = time.perf_counter()
        attempts = 0
        for target in self.alternatives:
            for attempt in range(retries + 1):
                attempts += 1
                try:
                    fn(target)
                    return FallbackResult(
                        ok=True,
                        target_id=str(target.get("id", target.get("target_id", ""))),
                        attempts=attempts,
                        duration_ms=round(elapsed_ms(started), 3),
                    )
                except Exception:  # noqa: BLE001 - try the next alternative
                    continue
        return FallbackResult(
            ok=False,
            attempts=attempts,
            detail="all alternatives failed",
            escalated=escalate_on_failure,
            duration_ms=round(elapsed_ms(started), 3),
        )

    def route_candidates(self) -> List[Dict[str, Any]]:
        return [dict(t) for t in self.alternatives]