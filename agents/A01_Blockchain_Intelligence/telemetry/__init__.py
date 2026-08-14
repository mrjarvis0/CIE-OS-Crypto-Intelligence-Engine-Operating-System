"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    telemetry

Purpose:
    Operational visibility, and the ability to get the data back.

Two questions
-------------
`metrics` answers **"is it working"** — blocks ingested, records rejected,
reorgs handled — and **"is it lying"**, which is the one specific to an
intelligence system.

A01 can be healthy by every conventional measure while producing conclusions
nobody should act on: a thin window, capped totals, no measured error rate.
None of those is an error and none will ever appear in a failure count, so they
are first-class series — `coverage_supports_absence`,
`conclusions_undetermined`, `alerts_suppressed`. An operator watching only
throughput would see a green dashboard over a system that has never been
allowed to conclude anything.

`backup` covers recovery. It uses SQLite's online backup API rather than a file
copy, because under WAL the committed state spans the database and its log, and
a copy taken mid-transaction produces a file that usually opens and is quietly
wrong. Every backup is verified on write — discovering at restore time that the
backup was never readable leaves nothing to fall back to.

Cardinality
-----------
Metric labels are restricted to a fixed set. A metric labelled by address grows
one series per address observed, which on a chain is unbounded by construction —
the classic way a metrics backend is taken down by the thing it monitors.
"""

from __future__ import annotations

from .backup import (
    BackupError,
    BackupResult,
    backup,
    restore,
    snapshot_name,
    verify,
)
from .metrics import ALLOWED_LABELS, MAX_SERIES, REGISTRY, Metric, MetricsRegistry

__all__ = [
    "ALLOWED_LABELS",
    "MAX_SERIES",
    "REGISTRY",
    "BackupError",
    "BackupResult",
    "Metric",
    "MetricsRegistry",
    "backup",
    "restore",
    "snapshot_name",
    "verify",
]
