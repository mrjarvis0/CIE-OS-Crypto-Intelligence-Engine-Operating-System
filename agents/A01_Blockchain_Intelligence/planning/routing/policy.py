"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.routing.policy

Purpose:
    Routing policies for the planning subsystem.

Policies filter the candidate set before a routing strategy runs,
enforcing constraints such as tool allow-lists, forbidden targets,
and capacity limits.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from planning.schemas import TaskSchema

logger = logging.getLogger("a01.planning.routing")

PolicyCheck = Callable[[TaskSchema, list[Any]], "PolicyDecision"]


@dataclass(slots=True)
class PolicyDecision:
    """
    Result of applying a routing policy.

    Fields:
        * Whether routing is allowed
        * Filtered candidate list
        * Reason when the route is blocked
    """

    allowed: bool = True
    candidates: list[Any] = field(default_factory=list)
    reason: str = ""


class RoutingPolicy:
    """
    Filters candidates before routing a task.

    Responsibilities:
        * Allow/deny by target id
        * Capacity limits
        * Custom predicate hooks
    """

    def __init__(self) -> None:
        self._allowed: set[str] | None = None
        self._denied: set[str] = set()
        self._capacity: dict[str, int] = {}
        self._usage: dict[str, int] = {}
        self._checks: list[PolicyCheck] = []

    def allow_only(self, target_ids: set[str] | None) -> None:
        """Restrict routing to the given target ids (None = no limit)."""
        self._allowed = set(target_ids) if target_ids is not None else None

    def deny(self, target_ids: set[str]) -> None:
        """Forbid routing to the given target ids."""
        self._denied |= set(target_ids)

    def set_capacity(self, target_id: str, limit: int) -> None:
        """Set the maximum concurrent routes for a target."""
        self._capacity[target_id] = limit

    def record_usage(self, target_id: str) -> None:
        """Record one route against a target's capacity."""
        self._usage[target_id] = self._usage.get(target_id, 0) + 1

    def add_check(self, check: PolicyCheck) -> None:
        """Register a custom policy predicate."""
        self._checks.append(check)

    def check(
        self,
        task: TaskSchema,
        candidates: list[Any],
    ) -> PolicyDecision:
        """Apply all policy rules to a candidate set."""

        filtered: list[Any] = []

        for candidate in candidates:
            target_id = getattr(candidate, "id", None)

            if self._allowed is not None and target_id not in self._allowed:
                continue

            if target_id in self._denied:
                continue

            capacity = self._capacity.get(target_id)
            usage = self._usage.get(target_id, 0)

            if capacity is not None and usage >= capacity:
                continue

            filtered.append(candidate)

        decision = PolicyDecision(
            allowed=True,
            candidates=filtered,
        )

        for check in self._checks:
            result = check(task, filtered)

            if not result.allowed:
                decision = result
                break

        return decision
