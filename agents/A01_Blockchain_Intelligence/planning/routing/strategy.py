"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.routing.strategy

Purpose:
    Routing strategy implementations for the planning subsystem.

Given a task and a set of candidates (agents or tools), a strategy
selects the best match. Strategies mirror ``RoutingStrategy``.
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from planning.schemas import TaskSchema
from planning.utils.constants import RoutingStrategy

logger = logging.getLogger("a01.planning.routing")

Scorer = Callable[[TaskSchema, Any], float]


class RouteCandidate(Protocol):
    """
    Protocol implemented by routable targets.

    Targets must expose an id and an optional description.
    """

    id: str
    description: str


def default_scorer(task: TaskSchema, candidate: Any) -> float:
    """
    Default scoring: score by keyword overlap between the task name /
    description and the candidate's description.
    """

    query = f"{task.name} {task.description}".lower()
    text = str(getattr(candidate, "description", "")).lower()

    if not text:
        return 0.0

    score = sum(
        1.0 for token in query.split() if token and token in text
    )
    return score


@dataclass(slots=True)
class RouteResult:
    """
    Outcome of a routing decision.

    Fields:
        * Selected candidate id (or None on failure)
        * Selected strategy name
        * Score of the selection
        * Candidates considered
    """

    candidate_id: str | None
    strategy: str
    score: float = 0.0
    candidates: list[str] = field(default_factory=list)


class RoutingStrategyImpl(ABC):
    """
    Base class for routing strategies.
    """

    name: str

    @abstractmethod
    def select(
        self,
        task: TaskSchema,
        candidates: list[Any],
        *,
        scorer: Scorer = default_scorer,
        random_source: random.Random | None = None,
    ) -> RouteResult:
        """
        Select a candidate for a task.

        Returns an empty ``candidate_id`` when no candidate qualifies.
        """


class FirstMatchStrategy(RoutingStrategyImpl):
    """
    Select the first candidate that scores above zero.

    Candidates are evaluated in registration order.
    """

    name = RoutingStrategy.FIRST_MATCH.value

    def select(
        self,
        task: TaskSchema,
        candidates: list[Any],
        *,
        scorer: Scorer = default_scorer,
        random_source: random.Random | None = None,
    ) -> RouteResult:
        if not candidates:
            return RouteResult(None, self.name)

        for candidate in candidates:
            score = scorer(task, candidate)

            if score > 0:
                return RouteResult(
                    candidate_id=candidate.id,
                    strategy=self.name,
                    score=score,
                    candidates=[candidate.id],
                )

        return RouteResult(None, self.name)


class BestScoreStrategy(RoutingStrategyImpl):
    """
    Select the candidate with the highest score.

    A candidate must score strictly above zero to qualify. Ties are
    broken by registration order.
    """

    name = RoutingStrategy.BEST_SCORE.value

    def select(
        self,
        task: TaskSchema,
        candidates: list[Any],
        *,
        scorer: Scorer = default_scorer,
        random_source: random.Random | None = None,
    ) -> RouteResult:
        if not candidates:
            return RouteResult(None, self.name)

        best: Any | None = None
        best_score = 0.0

        for candidate in candidates:
            score = scorer(task, candidate)

            if score > best_score:
                best = candidate
                best_score = score

        if best is None:
            return RouteResult(None, self.name)

        return RouteResult(
            candidate_id=best.id,
            strategy=self.name,
            score=best_score,
            candidates=[best.id],
        )


class RoundRobinStrategy(RoutingStrategyImpl):
    """
    Select candidates in rotation, ignoring scores.

    Used to distribute load evenly across equivalent targets.
    """

    name = RoutingStrategy.ROUND_ROBIN.value

    def __init__(self) -> None:
        self._index: dict[str, int] = {}

    def select(
        self,
        task: TaskSchema,
        candidates: list[Any],
        *,
        scorer: Scorer = default_scorer,
        random_source: random.Random | None = None,
    ) -> RouteResult:
        if not candidates:
            return RouteResult(None, self.name)

        key = task.goal_id or task.plan_id or task.id
        index = self._index.get(key, 0) % len(candidates)
        candidate = candidates[index]
        self._index[key] = index + 1

        return RouteResult(
            candidate_id=candidate.id,
            strategy=self.name,
            score=0.0,
            candidates=[candidate.id],
        )


class RandomStrategy(RoutingStrategyImpl):
    """
    Select a uniformly random candidate.
    """

    name = RoutingStrategy.RANDOM.value

    def select(
        self,
        task: TaskSchema,
        candidates: list[Any],
        *,
        scorer: Scorer = default_scorer,
        random_source: random.Random | None = None,
    ) -> RouteResult:
        if not candidates:
            return RouteResult(None, self.name)

        rng = random_source or random
        candidate = rng.choice(candidates)

        return RouteResult(
            candidate_id=candidate.id,
            strategy=self.name,
            score=0.0,
            candidates=[candidate.id],
        )


class FallbackStrategy(RoutingStrategyImpl):
    """
    Best-score first, falling back to the first candidate.

    Useful when a best-effort route is always acceptable.
    """

    name = RoutingStrategy.FALLBACK.value

    def select(
        self,
        task: TaskSchema,
        candidates: list[Any],
        *,
        scorer: Scorer = default_scorer,
        random_source: random.Random | None = None,
    ) -> RouteResult:
        if not candidates:
            return RouteResult(None, self.name)

        best = BestScoreStrategy().select(
            task,
            candidates,
            scorer=scorer,
            random_source=random_source,
        )

        if best.candidate_id is not None:
            return best

        candidate = candidates[0]
        return RouteResult(
            candidate_id=candidate.id,
            strategy=self.name,
            score=0.0,
            candidates=[candidate.id],
        )


_STRATEGY_FACTORIES: dict[str, Callable[[], RoutingStrategyImpl]] = {
    RoutingStrategy.FIRST_MATCH.value: FirstMatchStrategy,
    RoutingStrategy.BEST_SCORE.value: BestScoreStrategy,
    RoutingStrategy.ROUND_ROBIN.value: RoundRobinStrategy,
    RoutingStrategy.RANDOM.value: RandomStrategy,
    RoutingStrategy.FALLBACK.value: FallbackStrategy,
}


def build_strategy(
    strategy: RoutingStrategy | str,
) -> RoutingStrategyImpl:
    """
    Instantiate a strategy from a ``RoutingStrategy`` or its value.

    Raises
    ------
    ValueError
        When the strategy name is unknown.
    """

    name = strategy.value if isinstance(strategy, RoutingStrategy) else strategy
    factory = _STRATEGY_FACTORIES.get(name)

    if factory is None:
        raise ValueError(f"unknown routing strategy: {name}")

    return factory()
