"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.reasoning.verifier

Purpose:
    Output verification for the planning subsystem.

Verifies task or plan outputs against acceptance criteria, ensuring
the produced results are complete and correct before success is
recorded.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from planning.schemas.base import _now

logger = logging.getLogger("a01.planning.reasoning")

CriterionCheck = Callable[[Any], bool]


@dataclass(slots=True)
class VerificationResult:
    """
    Outcome of verifying an output.

    Fields:
        * Reference identifier
        * Per-criterion outcomes
        * Overall verified flag
        * Verification timestamp
    """

    reference_id: str
    outcomes: dict[str, bool] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    verified_at: datetime = field(default_factory=_now)

    @property
    def verified(self) -> bool:
        """Whether all criteria passed."""
        return bool(self.outcomes) and all(self.outcomes.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "verified": self.verified,
            "outcomes": dict(self.outcomes),
            "notes": dict(self.notes),
            "verified_at": self.verified_at.isoformat(),
        }


class Verifier:
    """
    Verifies outputs against registered criteria.

    Responsibilities:
        * Criterion registration
        * Output verification
        * Finding collection
    """

    def __init__(self) -> None:
        self._criteria: dict[str, CriterionCheck] = {}

    def register(self, name: str, check: CriterionCheck) -> None:
        """Register a named verification criterion."""
        self._criteria[name] = check

    def verify(
        self,
        reference_id: str,
        output: Any,
        *,
        criteria: dict[str, CriterionCheck] | None = None,
    ) -> VerificationResult:
        """
        Verify an output against registered (or provided) criteria.

        Raises
        ------
        ValueError
            When no criteria are available to verify against.
        """

        active = criteria or self._criteria

        if not active:
            raise ValueError(
                "no verification criteria registered for "
                f"{reference_id!r}"
            )

        result = VerificationResult(reference_id=reference_id)

        for name, check in active.items():
            try:
                passed = bool(check(output))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "verification criterion %r failed: %s",
                    name,
                    exc,
                )
                passed = False
                result.notes[name] = str(exc)

            result.outcomes[name] = passed

        logger.info(
            "output %s verified: %s",
            reference_id,
            "verified" if result.verified else "not verified",
        )
        return result
