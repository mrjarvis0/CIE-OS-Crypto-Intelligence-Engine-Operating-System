"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.routing.router

Purpose:
    Central routing orchestrator for the planning subsystem.

Routes a task to the best-matching target using a configured routing
strategy and optional policy checks.
"""

from __future__ import annotations

import logging
import random
from typing import Any

from planning.schemas import TaskSchema
from planning.utils.constants import RoutingStrategy

from .policy import RoutingPolicy, PolicyDecision
from .strategy import (
    RouteResult,
    RoutingStrategyImpl,
    Scorer,
    build_strategy,
    default_scorer,
)

logger = logging.getLogger("a01.planning.routing")


class RoutingError(Exception):
    """
    Base class for routing failures.
    """


class NoRouteFoundError(RoutingError):
    """
    Raised when no candidate can serve a task.
    """


class Router:
    """
    Routes tasks to registered targets (tools or agents).

    Responsibilities:
        * Target registration
        * Strategy dispatch
        * Policy enforcement
        * Route result reporting
    """

    def __init__(
        self,
        *,
        strategy: RoutingStrategy | str = RoutingStrategy.FIRST_MATCH,
        policy: RoutingPolicy | None = None,
        scorer: Scorer | None = None,
    ) -> None:
        self._strategy = build_strategy(strategy)
        self._policy = policy
        self._scorer = scorer or default_scorer
        self._targets: dict[str, Any] = {}
        self._rng = random.Random()

    @property
    def strategy(self) -> RoutingStrategyImpl:
        """The active routing strategy."""
        return self._strategy

    @property
    def targets(self) -> dict[str, Any]:
        """Read-only view of registered targets by id."""
        return dict(self._targets)

    def set_strategy(self, strategy: RoutingStrategy | str) -> None:
        """Replace the active routing strategy."""
        self._strategy = build_strategy(strategy)

    def set_scorer(self, scorer: Scorer) -> None:
        """Replace the scoring function."""
        self._scorer = scorer

    def set_policy(self, policy: RoutingPolicy) -> None:
        """Replace the routing policy."""
        self._policy = policy

    def register(self, target: Any) -> None:
        """Register a routable target."""
        target_id = getattr(target, "id", None)

        if not target_id:
            raise RoutingError("target must expose an id attribute")

        self._targets[target_id] = target
        logger.info("routing target registered: %s", target_id)

    def register_many(self, targets: list[Any]) -> None:
        """Register multiple routable targets."""
        for target in targets:
            self.register(target)

    def unregister(self, target_id: str) -> None:
        """Remove a registered target."""
        if target_id not in self._targets:
            raise RoutingError(f"target not registered: {target_id}")
        del self._targets[target_id]

    def route(
        self,
        task: TaskSchema,
        *,
        targets: list[Any] | None = None,
        strict: bool = False,
    ) -> RouteResult:
        """
        Route a task to the best candidate.

        Parameters
        ----------
        targets
            Optional override candidate list. Defaults to all registered
            targets.
        strict
            When true, a failed route raises NoRouteFoundError.

        Raises
        ------
        NoRouteFoundError
            When no candidate qualifies and ``strict`` is true.
        """

        candidates = targets if targets is not None else list(self._targets.values())

        if not candidates:
            if strict:
                raise NoRouteFoundError(f"no routing targets for task {task.id}")
            return RouteResult(None, self._strategy.name)

        if self._policy is not None:
            decision: PolicyDecision = self._policy.check(task, candidates)

            if not decision.allowed:
                if strict:
                    raise NoRouteFoundError(decision.reason)
                return RouteResult(None, self._strategy.name)

            candidates = decision.candidates

            if not candidates:
                if strict:
                    raise NoRouteFoundError(
                        "policy filtered out all routing candidates"
                    )
                return RouteResult(None, self._strategy.name)

        result = self._strategy.select(
            task,
            candidates,
            scorer=self._scorer,
            random_source=self._rng,
        )

        if result.candidate_id is None and strict:
            raise NoRouteFoundError(
                f"no route for task {task.id} under "
                f"{self._strategy.name}"
            )

        logger.info(
            "task %s routed to %s via %s",
            task.id,
            result.candidate_id,
            self._strategy.name,
        )
        return result
