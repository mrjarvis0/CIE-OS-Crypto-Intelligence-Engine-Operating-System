"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.core.dispatcher

Purpose:
    Task dispatch for the planning subsystem.

Routes tasks to registered targets (tools or agents) using the
routing subsystem, and records routing outcomes.
"""

from __future__ import annotations

import logging
from typing import Any

from planning.schemas import TaskSchema
from planning.utils.constants import EventType

from .context import PlanningContext

logger = logging.getLogger("a01.planning.core")


class DispatchError(Exception):
    """
    Base class for dispatch failures.
    """


class NoTargetError(DispatchError):
    """
    Raised when no target is available for a task.
    """


class Dispatcher:
    """
    Routes and dispatches tasks.

    Responsibilities:
        * Target registration
        * Task routing
        * Outcome recording
    """

    def __init__(self, context: PlanningContext) -> None:
        self._context = context

    @property
    def context(self) -> PlanningContext:
        """The bound planning context."""
        return self._context

    def register_target(self, target: Any) -> None:
        """Register a routable target (tool or agent)."""
        self._context.router.register(target)

    async def dispatch(self, task: TaskSchema) -> Any:
        """
        Route a task and return the selected target.

        Raises
        ------
        NoTargetError
            When the router cannot find a target.
        """

        route = self._context.router.route(task, strict=True)

        if route.candidate_id is None:
            raise NoTargetError(f"no target for task {task.id}")

        self._context.metrics.inc("tasks_dispatched")
        await self._context.events.emit(
            type_event(EventType.TOOL_SELECTED, task),
        )
        return self._context.router.targets[route.candidate_id]


def type_event(event_type: EventType, task: TaskSchema) -> Any:
    """Build a PlanEvent for a task."""
    from planning.monitoring import PlanEvent

    return PlanEvent(
        type=event_type,
        plan_id=task.plan_id,
        task_id=task.id,
        source="dispatcher",
    )
