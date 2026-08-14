"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.core.runtime

Purpose:
    Runtime composition for the planning subsystem.

Binds the context, planner, dispatcher, executor, lifecycle,
coordinator, and orchestrator into a single entry point.
"""

from __future__ import annotations

import logging
from typing import Any

from .context import PlanningContext
from .coordinator import Coordinator, PlanOutcome
from .dispatcher import Dispatcher
from .executor import PlanExecutor
from .orchestrator import Orchestrator
from .planner import Planner

logger = logging.getLogger("a01.planning.core")


class PlanningRuntime:
    """
    Composed planning runtime.

    Responsibilities:
        * Component wiring
        * Public entry points
        * Lifecycle management
    """

    def __init__(
        self,
        *,
        task_handler: Any = None,
        max_concurrent: int = 10,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.context = PlanningContext(
            task_handler=task_handler,
            max_concurrent=max_concurrent,
            config=config,
        )
        self.planner = Planner(self.context)
        self.dispatcher = Dispatcher(self.context)
        self.executor = PlanExecutor(self.context)
        self.lifecycle = self.context.lifecycle
        self.coordinator = Coordinator(self.context)
        self.orchestrator = Orchestrator(self.context)

    async def run_goal(
        self,
        goal: Any,
        *,
        plan_id: str | None = None,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PlanOutcome:
        """Run a goal through the full planning pipeline."""
        return await self.orchestrator.run_goal(
            goal,
            plan_id=plan_id,
            name=name,
            metadata=metadata,
        )

    async def close(self) -> None:
        """Reset volatile runtime state."""
        self.lifecycle.reset()
        await self.context.tasks.clear()
        await self.context.goals.clear()
        self.context.metrics.reset()
        logger.info("planning runtime closed")

    @property
    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot of the runtime."""
        return self.context.snapshot()
