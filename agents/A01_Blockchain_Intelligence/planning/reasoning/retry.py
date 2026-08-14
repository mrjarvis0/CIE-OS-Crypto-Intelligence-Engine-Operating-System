"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.reasoning.retry

Purpose:
    Retry decisioning for the planning subsystem.

Analyzes task failures to decide whether a retry is worthwhile,
factoring in retry policy, attempt budget, and error type.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from planning.schemas import TaskSchema
from planning.utils.constants import RetryPolicy

logger = logging.getLogger("a01.planning.reasoning")


class RetryError(Exception):
    """
    Base class for retry decisioning failures.
    """


@dataclass(slots=True)
class RetryDecision:
    """
    Decision about whether to retry a failed task.

    Fields:
        * Should-retry flag
        * Reason for the decision
        * Suggested delay (seconds)
        * Remaining attempts
    """

    should_retry: bool
    reason: str
    suggested_delay: float = 0.0
    remaining_attempts: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_retry": self.should_retry,
            "reason": self.reason,
            "suggested_delay": self.suggested_delay,
            "remaining_attempts": self.remaining_attempts,
        }


# Error types that are worth retrying (transient failures).
_TRANSIENT_MARKERS = (
    "timeout",
    "connection",
    "temporarily unavailable",
    "too many requests",
    "rate limit",
    "service unavailable",
)


class RetryAnalyzer:
    """
    Decides whether a failed task should be retried.

    Responsibilities:
        * Attempt budget checks
        * Transient error classification
        * Retry policy enforcement
    """

    def decide(
        self,
        task: TaskSchema,
        *,
        error: str | None = None,
        attempts_used: int = 0,
    ) -> RetryDecision:
        """
        Decide whether to retry a failed task.

        Parameters
        ----------
        task
            The failed task.
        error
            The error message from the last attempt.
        attempts_used
            Number of attempts already consumed.
        """

        if task.retry_policy == RetryPolicy.NONE:
            return RetryDecision(
                False,
                "retry disabled by policy",
                remaining_attempts=0,
            )

        if attempts_used >= task.max_retries:
            return RetryDecision(
                False,
                "retry budget exhausted",
                remaining_attempts=0,
            )

        if task.retry_policy == RetryPolicy.ALWAYS:
            remaining = task.max_retries - attempts_used
            return RetryDecision(
                True,
                "always-retry policy",
                remaining_attempts=remaining,
            )

        if error and self._is_transient(error):
            remaining = task.max_retries - attempts_used
            return RetryDecision(
                True,
                "transient failure detected",
                remaining_attempts=remaining,
            )

        return RetryDecision(
            False,
            "failure is not retryable",
            remaining_attempts=0,
        )

    @staticmethod
    def _is_transient(error: str) -> bool:
        lowered = error.lower()
        return any(marker in lowered for marker in _TRANSIENT_MARKERS)
