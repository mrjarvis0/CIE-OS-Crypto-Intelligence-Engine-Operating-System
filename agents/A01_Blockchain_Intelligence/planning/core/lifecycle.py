"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.core.lifecycle

Purpose:
    Plan lifecycle management for the planning subsystem.

Enforces the high-level state transitions of a plan (``PlanningState``)
and tracks the active state per plan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from planning.schemas import PlanSchema
from planning.utils.constants import PlanningState

from .context import PlanningContext

logger = logging.getLogger("a01.planning.core")


class LifecycleError(Exception):
    """
    Base class for lifecycle failures.
    """


class InvalidTransitionError(LifecycleError):
    """
    Raised when a plan state transition is not allowed.
    """


# Allowed plan state transitions.
_PLAN_TRANSITIONS: dict[PlanningState, set[PlanningState]] = {
    PlanningState.CREATED: {
        PlanningState.UNDERSTANDING,
        PlanningState.PLANNING,
        PlanningState.CANCELLED,
        PlanningState.FAILED,
    },
    PlanningState.UNDERSTANDING: {
        PlanningState.PLANNING,
        PlanningState.CANCELLED,
        PlanningState.FAILED,
    },
    PlanningState.PLANNING: {
        PlanningState.SCHEDULED,
        PlanningState.REPLANNING,
        PlanningState.CANCELLED,
        PlanningState.FAILED,
    },
    PlanningState.SCHEDULED: {
        PlanningState.EXECUTING,
        PlanningState.CANCELLED,
        PlanningState.FAILED,
    },
    PlanningState.EXECUTING: {
        PlanningState.VALIDATING,
        PlanningState.REPLANNING,
        PlanningState.CANCELLED,
        PlanningState.FAILED,
    },
    PlanningState.VALIDATING: {
        PlanningState.REFLECTING,
        PlanningState.REPLANNING,
        PlanningState.COMPLETED,
        PlanningState.CANCELLED,
        PlanningState.FAILED,
    },
    PlanningState.REFLECTING: {
        PlanningState.COMPLETED,
        PlanningState.REPLANNING,
        PlanningState.CANCELLED,
        PlanningState.FAILED,
    },
    PlanningState.REPLANNING: {
        PlanningState.SCHEDULED,
        PlanningState.EXECUTING,
        PlanningState.CANCELLED,
        PlanningState.FAILED,
    },
    PlanningState.COMPLETED: set(),
    PlanningState.FAILED: set(),
    PlanningState.CANCELLED: set(),
}


@dataclass(slots=True)
class LifecycleState:
    """
    Tracked lifecycle of a single plan.

    Fields:
        * Plan identifier and current state
        * Transition history
    """

    plan_id: str
    state: PlanningState = PlanningState.CREATED
    history: list[str] = field(default_factory=list)


class PlanLifecycle:
    """
    Enforces plan state transitions.

    Responsibilities:
        * Transition validation
        * State persistence
        * History recording
    """

    def __init__(self, context: PlanningContext) -> None:
        self._context = context
        self._states: dict[str, LifecycleState] = {}

    def get(self, plan_id: str) -> LifecycleState | None:
        """Return the tracked lifecycle state for a plan."""
        return self._states.get(plan_id)

    def register(
        self,
        plan: PlanSchema | None = None,
        *,
        plan_id: str | None = None,
    ) -> LifecycleState:
        """Register a new plan in CREATED state."""
        identifier = (plan.id if plan is not None else plan_id) or ""

        if identifier in self._states:
            return self._states[identifier]

        state = LifecycleState(plan_id=identifier)
        state.history.append(identifier)
        self._states[identifier] = state
        return state

    def transition(
        self,
        plan_id: str,
        target: PlanningState,
    ) -> LifecycleState:
        """
        Transition a plan to a new state.

        Raises
        ------
        InvalidTransitionError
            When the transition is not allowed.
        UnknownPlanError
            When the plan is not registered.
        """

        state = self._states.get(plan_id)

        if state is None:
            raise LifecycleError(f"plan not registered: {plan_id}")

        if target == state.state:
            return state

        allowed = _PLAN_TRANSITIONS.get(state.state, set())

        if target not in allowed:
            raise InvalidTransitionError(
                f"invalid plan transition: "
                f"{state.state.value} -> {target.value}"
            )

        state.state = target
        state.history.append(target.value)
        logger.info("plan %s transitioned to %s", plan_id, target.value)
        return state

    def reset(self) -> None:
        """Forget all tracked lifecycle states."""
        self._states.clear()
