"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.verification.verifier

Purpose:
    Central verification orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class VerificationResult:
    """
    Result of verifying a claim across one or more checks.
    """

    claim: str
    confirmed: bool
    confidence: float = 0.0
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "confirmed": self.confirmed,
            "confidence": self.confidence,
            "checks": self.checks,
        }


class Verifier:
    """
    Runs registered verification checks for a claim.

    Confirmation uses a configurable consensus threshold (default 1.0 =
    all checks must pass; lower values allow majority confirmation). The
    aggregate confidence is the confirmed fraction.
    """

    def __init__(self, threshold: float = 1.0) -> None:
        self._checks: list[tuple[str, Callable[[str], bool]]] = []
        self._threshold = threshold

    def add_check(self, name: str, check: Callable[[str], bool]) -> "Verifier":
        """
        Register a named verification check.
        """
        self._checks.append((name, check))
        return self

    def verify(self, claim: str) -> VerificationResult:
        """
        Run all checks and aggregate results.
        """
        results: dict[str, bool] = {}
        for name, check in self._checks:
            try:
                results[name] = bool(check(claim))
            except Exception:  # noqa: BLE001
                results[name] = False
        ratio = sum(results.values()) / len(results) if results else 0.0
        confirmed = ratio >= self._threshold if results else False
        return VerificationResult(
            claim=claim,
            confirmed=confirmed,
            confidence=ratio,
            checks=results,
        )
