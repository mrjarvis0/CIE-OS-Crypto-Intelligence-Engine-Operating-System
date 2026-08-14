"""
Tools :: Monitoring :: Metrics
==============================

Quantitative runtime measurements: counts, latencies, rates, gauges and
histograms with incremental aggregation.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["Metric", "MetricKind", "MetricsRegistry"]


class MetricKind:
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class Metric:
    """One named metric with kind-aware aggregation."""

    def __init__(self, name: str, kind: str = MetricKind.COUNTER, labels: Optional[Mapping[str, str]] = None) -> None:
        self.name = name
        self.kind = kind
        self.labels = dict(labels or {})
        self._count = 0
        self._sum = 0.0
        self._value = 0.0
        self._buckets: List[float] = []

    # -- updates ----------------------------------------------------------------- #

    def increment(self, amount: float = 1.0) -> None:
        self._count += 1
        self._sum += amount
        self._value += amount

    def set(self, value: float) -> None:
        self._value = float(value)

    def observe(self, value: float) -> None:
        self._count += 1
        self._sum += value
        self._buckets.append(float(value))
        self._value = float(value)

    # -- reads -------------------------------------------------------------------- #

    @property
    def count(self) -> int:
        return self._count

    @property
    def value(self) -> float:
        return self._value

    @property
    def sum(self) -> float:
        return self._sum

    @property
    def mean(self) -> float:
        return self._sum / self._count if self._count else 0.0

    def snapshot(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "labels": dict(self.labels),
            "count": self._count,
            "value": self._value,
            "sum": self._sum,
        }
        if self.kind == MetricKind.HISTOGRAM:
            data["mean"] = self.mean
            if self._buckets:
                data["min"] = min(self._buckets)
                data["max"] = max(self._buckets)
                data["p50"] = sorted(self._buckets)[len(self._buckets) // 2]
        return data


class MetricsRegistry:
    """Named metric store with label-keyed variants."""

    def __init__(self) -> None:
        self._metrics: Dict[str, Metric] = {}

    def _key(self, name: str, labels: Mapping[str, str]) -> str:
        if labels:
            suffix = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
            return f"{name}{{{suffix}}}"
        return name

    def get(self, name: str, *, kind: str = MetricKind.COUNTER, labels: Optional[Mapping[str, str]] = None) -> Metric:
        key = self._key(name, labels or {})
        metric = self._metrics.get(key)
        if metric is None:
            metric = Metric(name, kind=kind, labels=labels)
            self._metrics[key] = metric
        return metric

    def increment(self, name: str, amount: float = 1.0, labels: Optional[Mapping[str, str]] = None) -> None:
        self.get(name, kind=MetricKind.COUNTER, labels=labels).increment(amount)

    def gauge(self, name: str, value: float, labels: Optional[Mapping[str, str]] = None) -> None:
        self.get(name, kind=MetricKind.GAUGE, labels=labels).set(value)

    def histogram(self, name: str, value: float, labels: Optional[Mapping[str, str]] = None) -> None:
        self.get(name, kind=MetricKind.HISTOGRAM, labels=labels).observe(value)

    def duration(self, name: str, seconds: float, labels: Optional[Mapping[str, str]] = None) -> None:
        self.histogram(name, seconds, labels)

    def success_rate(self, name: str, *, attempts: int, failures: int) -> float:
        return (attempts - failures) / attempts if attempts else 1.0

    def snapshot(self, prefix: str = "") -> List[Dict[str, Any]]:
        return [metric.snapshot() for name, metric in sorted(self._metrics.items()) if name.startswith(prefix)]

    def reset(self) -> None:
        self._metrics.clear()