"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    telemetry.metrics

Purpose:
    Collect what an operator needs to answer "is it working, and is it lying?"

Design goals:
    - Counters and gauges only; no sampling, no aggregation windows
    - Bounded cardinality, so a label cannot grow without limit
    - Exported in a text format with no dependency
    - Reads state the layers already track rather than duplicating it
    - Never raises; a broken metric must not take down what it measures

Notes:
    Two questions matter for this agent, and only the first is the usual one.

    "Is it working" is throughput and errors: blocks ingested, records rejected,
    reorgs handled. Standard, and covered.

    "Is it lying" is the one specific to an intelligence system, and it is the
    reason this module reports things a normal service would not. A01 can be
    perfectly healthy by every conventional measure while producing conclusions
    nobody should act on — thin coverage, capped totals, an unmeasured error
    rate. Those are not errors and will never appear in a failure count, so they
    are surfaced as first-class metrics: ``coverage_supports_absence``,
    ``conclusions_undetermined``, ``alerts_suppressed_unvalidated``.

    An operator watching only the first set would see a green dashboard over a
    system that has never been allowed to conclude anything.

    Label cardinality is bounded deliberately. A metric labelled by address
    would grow one series per address observed, which on a chain is unbounded by
    construction — the classic way a metrics backend is taken down by the thing
    it monitors.
"""

from __future__ import annotations

import logging
import threading

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Mapping

logger = logging.getLogger(__name__)

#: Labels permitted on a metric. Anything with unbounded values -- an address,
#: a transaction hash, a block height -- is excluded by construction.
ALLOWED_LABELS: Final[frozenset[str]] = frozenset({"chain", "detector", "skill", "outcome"})

#: Ceiling on distinct label combinations per metric. A breach means a label
#: escaped its intended domain, which is worth a warning rather than silent
#: unbounded growth.
MAX_SERIES: Final[int] = 256


def _key(labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((k, str(v)) for k, v in labels.items()))


@dataclass
class Metric:
    """One named measurement across its label combinations."""

    name: str
    help_text: str
    kind: str = "counter"
    values: dict[tuple[tuple[str, str], ...], float] = field(default_factory=dict)

    def as_lines(self) -> list[str]:
        """Prometheus text exposition, which is the de facto plain format."""
        lines = [f"# HELP a01_{self.name} {self.help_text}", f"# TYPE a01_{self.name} {self.kind}"]
        for labels, value in sorted(self.values.items()):
            rendered = (
                "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}" if labels else ""
            )
            lines.append(f"a01_{self.name}{rendered} {value:g}")
        return lines


class MetricsRegistry:
    """
    The metrics A01 exposes.

    Thread-safe because the REST API serves on a threading server, and a
    scrape landing mid-increment on an unsynchronised dict is exactly the kind
    of rare corruption that is impossible to reproduce later.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}
        self._lock = threading.Lock()
        self._started = datetime.now(UTC)

    # -- recording --------------------------------------------------------

    def counter(
        self,
        name: str,
        help_text: str = "",
        *,
        labels: Mapping[str, str] | None = None,
        amount: float = 1.0,
    ) -> None:
        """Increment a monotonic counter."""
        self._record(name, help_text, "counter", labels, amount, accumulate=True)

    def gauge(
        self,
        name: str,
        value: float,
        help_text: str = "",
        *,
        labels: Mapping[str, str] | None = None,
    ) -> None:
        """Set a value that can go down as well as up."""
        self._record(name, help_text, "gauge", labels, value, accumulate=False)

    def _record(
        self,
        name: str,
        help_text: str,
        kind: str,
        labels: Mapping[str, str] | None,
        value: float,
        *,
        accumulate: bool,
    ) -> None:
        rejected = set(labels or {}) - ALLOWED_LABELS
        if rejected:
            # Dropped rather than recorded. An address label would create one
            # series per address seen, which is unbounded on a chain.
            logger.warning(
                "metric %s: dropping unbounded label(s) %s", name, sorted(rejected)
            )
            labels = {k: v for k, v in (labels or {}).items() if k in ALLOWED_LABELS}

        key = _key(labels)
        with self._lock:
            metric = self._metrics.get(name)
            if metric is None:
                metric = Metric(name=name, help_text=help_text or name, kind=kind)
                self._metrics[name] = metric

            if key not in metric.values and len(metric.values) >= MAX_SERIES:
                logger.warning(
                    "metric %s exceeded %d series; dropping new label set",
                    name,
                    MAX_SERIES,
                )
                return

            if accumulate:
                metric.values[key] = metric.values.get(key, 0.0) + value
            else:
                metric.values[key] = value

    # -- observation ------------------------------------------------------

    def observe_writer(self, writer: Any, *, chain: str = "ethereum") -> None:
        """Record what the ingestion writer has done. Never raises."""
        try:
            stats = writer.stats
            labels = {"chain": chain}
            self.gauge("blocks_written", stats.written, "Blocks stored", labels=labels)
            self.gauge(
                "transactions_written",
                stats.transactions_written,
                "Transactions stored",
                labels=labels,
            )
            self.gauge(
                "records_rejected",
                stats.rejected,
                "Records refused by normalization",
                labels=labels,
            )
            self.gauge(
                "blocks_withdrawn",
                stats.withdrawn_blocks,
                "Blocks withdrawn by a reorg",
                labels=labels,
            )
        except Exception as exc:  # noqa: BLE001 - telemetry must not break the pipeline
            logger.warning("failed to observe writer: %s", exc)

    def observe_decision(self, decision: Any) -> None:
        """
        Record the honesty metrics, not just the throughput ones.

        These are the series that show A01 is healthy *and* unable to conclude
        anything — a state no conventional health check reports, because
        nothing has failed.
        """
        try:
            self.gauge(
                "conclusions_actionable",
                len(decision.actionable),
                "Conclusions supported well enough to act on",
            )
            self.gauge(
                "conclusions_undetermined",
                len(decision.undetermined),
                "Questions the evidence could not answer",
            )
            for reason, count in decision.alerts.reasons().items():
                self.gauge(
                    "alerts_suppressed",
                    count,
                    "Alerts withheld, by reason",
                    labels={"outcome": reason},
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to observe decision: %s", exc)

    def observe_coverage(self, coverage: Any, *, chain: str = "ethereum") -> None:
        """Record whether stored history can support a negative claim."""
        try:
            labels = {"chain": chain}
            self.gauge("coverage_blocks", coverage.blocks, "Blocks stored", labels=labels)
            self.gauge(
                "coverage_supports_absence",
                1.0 if coverage.supports_absence else 0.0,
                "1 when the window can license a negative finding",
                labels=labels,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to observe coverage: %s", exc)

    # -- export -----------------------------------------------------------

    @property
    def uptime_seconds(self) -> float:
        return (datetime.now(UTC) - self._started).total_seconds()

    def render(self) -> str:
        """Prometheus text exposition of everything recorded."""
        with self._lock:
            metrics = list(self._metrics.values())

        lines: list[str] = [
            "# HELP a01_uptime_seconds Seconds since this process started",
            "# TYPE a01_uptime_seconds gauge",
            f"a01_uptime_seconds {self.uptime_seconds:g}",
        ]
        for metric in sorted(metrics, key=lambda m: m.name):
            lines.extend(metric.as_lines())
        return "\n".join(lines) + "\n"

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "uptime_seconds": round(self.uptime_seconds, 3),
                "metrics": {
                    name: {
                        "type": metric.kind,
                        "help": metric.help_text,
                        "series": {
                            ("{" + ",".join(f"{k}={v}" for k, v in labels) + "}")
                            if labels
                            else "_": value
                            for labels, value in metric.values.items()
                        },
                    }
                    for name, metric in self._metrics.items()
                },
            }

    def reset(self) -> None:
        """Clear everything. For tests; a running agent never calls this."""
        with self._lock:
            self._metrics.clear()

    def __len__(self) -> int:
        return len(self._metrics)

    def __repr__(self) -> str:
        return f"MetricsRegistry(metrics={len(self._metrics)})"


#: Process-wide registry. A single instance because metrics describe the
#: process, and a per-request registry would report zero for everything.
REGISTRY = MetricsRegistry()


__all__ = ["ALLOWED_LABELS", "MAX_SERIES", "REGISTRY", "Metric", "MetricsRegistry"]
