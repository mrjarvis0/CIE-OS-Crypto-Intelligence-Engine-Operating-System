"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    normalization

Purpose:
    The boundary where a provider's payload becomes A01's record.

Layer contract
--------------
Design rule DR-08 requires external data to pass validation, normalization and
deduplication before storage, and states that raw external data must never be
trusted. Deduplication happens upstream in :mod:`ingestion.dedup`; the other two
happen here.

The distinction that governs this package is between **refusing** and
**annotating**:

* :mod:`normalization.evm` refuses. A payload that cannot state which block it
  is, what it follows, or when it happened is not a weaker observation -- it is
  not an observation, and nothing here substitutes a default to rescue it.
* :mod:`normalization.quality` annotates. A block fetched without expanded
  transactions is perfectly usable for tracking progress; it is only dangerous
  if a reader mistakes it for complete. So findings travel with the record and
  say what must not be inferred from it.

Nothing above this layer sees a provider's field names. That is what makes
adding a chain a normalizer change rather than a change to every detector.
"""

from __future__ import annotations

from .evm import normalize_block, normalize_transaction, read_quantity
from .logs import normalize_logs
from .normalizer import NormalizationResult, Normalizer, NormalizerStats
from .quality import (
    MAX_FUTURE_DRIFT,
    MIN_PLAUSIBLE_TIMESTAMP,
    QualityFinding,
    QualityReport,
    Severity,
    assess_block,
)

__all__ = [
    "MAX_FUTURE_DRIFT",
    "MIN_PLAUSIBLE_TIMESTAMP",
    "NormalizationResult",
    "Normalizer",
    "NormalizerStats",
    "QualityFinding",
    "QualityReport",
    "Severity",
    "assess_block",
    "normalize_block",
    "normalize_logs",
    "normalize_transaction",
    "read_quantity",
]
