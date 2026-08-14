"""
Tools :: Routing :: Balancing
=============================

Distributes workload across providers: load balancing, queue balancing,
rate-limit awareness, provider distribution and resource optimization.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["BalancerStats", "LoadBalancer"]


@dataclass
class BalancerStats:
    """Per-target usage statistics."""

    target_id: str
    weight: float = 1.0
    in_flight: int = 0
    total: int = 0
    failures: int = 0
    rate_limit: Optional[int] = None
    last_pick: int = 0

    @property
    def load(self) -> float:
        base = self.in_flight * 1.0 / max(0.1, self.weight)
        if self.rate_limit and self.total >= self.rate_limit:
            base += 10.0
        return round(base, 3)


class LoadBalancer:
    """Deterministic workload distributor with round-robin and
    least-loaded strategies."""

    def __init__(self, mode: str = "round_robin") -> None:
        if mode not in ("round_robin", "least_loaded"):
            raise ValueError(f"unsupported balancing mode {mode!r}")
        self.mode = mode
        self._stats: Dict[str, BalancerStats] = {}
        self._cycle = itertools.count()

    def register(self, target_id: str, *, weight: float = 1.0, rate_limit: Optional[int] = None) -> None:
        self._stats.setdefault(target_id, BalancerStats(target_id=target_id, weight=weight, rate_limit=rate_limit))

    def pick(self) -> Optional[str]:
        """Pick the next target according to the balancing mode."""
        if not self._stats:
            return None
        if self.mode == "round_robin":
            targets = list(self._stats)
            index = next(self._cycle) % len(targets)
            return targets[index]
        return min(self._stats, key=lambda tid: (self._stats[tid].load, self._stats[tid].total))

    def begin(self, target_id: str) -> None:
        self.register(target_id)
        self._stats[target_id].in_flight += 1

    def end(self, target_id: str, *, failed: bool = False) -> None:
        stats = self._stats.get(target_id)
        if stats is None:
            return
        stats.in_flight = max(0, stats.in_flight - 1)
        stats.total += 1
        if failed:
            stats.failures += 1

    def stats(self) -> List[Dict[str, Any]]:
        return [
            {
                "target_id": s.target_id,
                "weight": s.weight,
                "in_flight": s.in_flight,
                "total": s.total,
                "failures": s.failures,
                "load": s.load,
            }
            for s in self._stats.values()
        ]

    def healthiest(self, exclude: Sequence[str] = ()) -> Optional[str]:
        excluded = set(exclude)
        candidates = [tid for tid in self._stats if tid not in excluded]
        if not candidates:
            return None
        return min(candidates, key=lambda tid: (self._stats[tid].load, self._stats[tid].failures))