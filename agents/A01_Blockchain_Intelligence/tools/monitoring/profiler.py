"""
Tools :: Monitoring :: Profiler
===============================

Performance profiling: CPU, memory, network, disk usage, execution
hotspots, slow tool detection and resource bottlenecks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["ProfileSample", "Profiler", "ProfileReport"]


@dataclass
class ProfileSample:
    """One measured execution profile."""

    name: str
    duration_ms: float
    cpu_usage: float = 0.0
    memory_mb: float = 0.0
    network_kb: float = 0.0
    disk_kb: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "cpu_usage": self.cpu_usage,
            "memory_mb": self.memory_mb,
            "network_kb": self.network_kb,
            "disk_kb": self.disk_kb,
            "timestamp": self.timestamp,
        }


@dataclass
class ProfileReport:
    """Aggregated statistics over samples."""

    samples: List[ProfileSample] = field(default_factory=list)

    @property
    def total_samples(self) -> int:
        return len(self.samples)

    def by_name(self, name: str) -> List[ProfileSample]:
        return [sample for sample in self.samples if sample.name == name]

    @property
    def hotspots(self) -> List[Dict[str, Any]]:
        aggregated: Dict[str, List[float]] = {}
        for sample in self.samples:
            aggregated.setdefault(sample.name, []).append(sample.duration_ms)
        rows = []
        for name, durations in aggregated.items():
            rows.append(
                {
                    "name": name,
                    "calls": len(durations),
                    "avg_ms": round(sum(durations) / len(durations), 3),
                    "max_ms": round(max(durations), 3),
                }
            )
        rows.sort(key=lambda r: r["avg_ms"], reverse=True)
        return rows

    def slow(self, threshold_ms: float = 1000.0) -> List[ProfileSample]:
        return [sample for sample in self.samples if sample.duration_ms >= threshold_ms]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "hotspots": self.hotspots,
            "slow_count": len(self.slow()),
            "total_samples": len(self.samples),
        }


class Profiler:
    """Collects execution profiles; use as a context manager."""

    def __init__(self) -> None:
        self._samples: List[ProfileSample] = []
        self._started_at: Optional[float] = None
        self._active: Optional[str] = None

    # -- manual ---------------------------------------------------------------- #

    def start(self, name: str) -> None:
        self._active = name
        self._started_at = time.perf_counter()

    def stop(self, **resources: float) -> ProfileSample:
        duration = (time.perf_counter() - self._started_at) * 1000 if self._started_at else 0.0
        sample = ProfileSample(
            name=self._active or "unknown",
            duration_ms=round(duration, 3),
            cpu_usage=float(resources.get("cpu", 0.0)),
            memory_mb=float(resources.get("memory", 0.0)),
            network_kb=float(resources.get("network", 0.0)),
            disk_kb=float(resources.get("disk", 0.0)),
        )
        self._samples.append(sample)
        self._active = None
        self._started_at = None
        return sample

    # -- context manager -------------------------------------------------------- #

    def __enter__(self) -> "Profiler":
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._active is not None:
            self.stop()

    # -- reporting ---------------------------------------------------------------- #

    def report(self) -> ProfileReport:
        return ProfileReport(samples=list(self._samples))

    def reset(self) -> None:
        self._samples.clear()