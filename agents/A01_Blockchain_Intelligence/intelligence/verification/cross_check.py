"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.verification.cross_check

Purpose:
    Cross-source claim checking.

    A claim is confirmed across every registered source; a single
    failing or raising source is recorded as ``False`` without
    aborting the remaining sources, mirroring the per-check isolation
    of :class:`~intelligence.verification.verifier.Verifier`.
"""

from __future__ import annotations

import logging
from typing import Any

from .verifier import VerificationResult

logger = logging.getLogger("a01.intelligence.verification")


class CrossChecker:
    """
    Cross-checks a claim by confirming it across multiple sources.
    """

    def __init__(self, sources: list[Any] | None = None) -> None:
        self._sources = list(sources or [])

    def add_source(self, source: Any) -> "CrossChecker":
        """
        Register a source exposing a `verify` method.
        """
        self._sources.append(source)
        return self

    def check(self, claim: str) -> VerificationResult:
        """
        Confirm the claim across all registered sources.

        Exceptions raised by a single source are logged and counted as
        a failed check; the remaining sources still contribute.
        """
        results: dict[str, bool] = {}
        for source in self._sources:
            verify = getattr(source, "verify", None)
            if verify is None:
                continue
            name = getattr(source, "name", type(source).__name__)
            try:
                results[name] = bool(verify(claim))
            except Exception as exc:  # noqa: BLE001 - source boundary
                logger.warning("cross-check source %s failed: %s", name, exc)
                results[name] = False
        confirmed = all(results.values()) if results else False
        ratio = sum(results.values()) / len(results) if results else 0.0
        return VerificationResult(
            claim=claim,
            confirmed=confirmed,
            confidence=ratio,
            checks=results,
        )
