"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.core.context

Purpose:
    Shared runtime context for the planning subsystem.

A dependency container that binds the managers, services, and
monitoring components so they can be composed without global state.
"""

from __future__ import annotations

import logging
from typing import Any

from planning.execution import (
    AsyncRunner,
    CheckpointManager,
    RecoveryService,
    TaskExecutor,
)
from planning.goals import (
    AssumptionManager,
    ConstraintManager,
    GoalManager,
    ObjectiveManager,
    SuccessEvaluator,
)
from planning.monitoring import (
    Diagnostics,
    EventBus,
    MetricsRegistry,
    ProgressTracker,
    Timeline,
    Tracer,
)
from planning.reasoning import (
    Critic,
    Evaluator,
    PlanValidator,
    Reflector,
    Replanner,
    RetryAnalyzer,
    Verifier,
)
from planning.routing import (
    AgentSelector,
    Router,
    RoutingPolicy,
    ToolSelector,
)
from planning.tasks import (
    DecompositionService,
    PlannerStateManager,
    TaskManager,
    TaskPrioritizer,
    TaskScheduler,
    WorkflowRegistry,
)

logger = logging.getLogger("a01.planning.core")


async def _noop_handler(task: Any) -> str:
    """Default task handler that marks execution without a real run."""
    return f"noop:{getattr(task, 'id', '?')}"


class PlanningContext:
    """
    Container for planning subsystem components.

    Responsibilities:
        * Constructing the standard component set
        * Holding shared monitoring primitives
        * Runtime configuration
    """

    def __init__(
        self,
        *,
        task_handler: Any = None,
        max_concurrent: int = 10,
        config: dict[str, Any] | None = None,
    ) -> None:
        # Monitoring
        self.events = EventBus()
        self.metrics = MetricsRegistry()
        self.tracer = Tracer()
        self.timeline = Timeline()
        self.progress = ProgressTracker()
        self.diagnostics = Diagnostics()

        # Managers
        self.goals = GoalManager()
        self.objectives = ObjectiveManager()
        self.assumptions = AssumptionManager()
        self.constraints = ConstraintManager()
        self.success = SuccessEvaluator()
        self.tasks = TaskManager()
        self.workflows = WorkflowRegistry()
        self.plan_states = PlannerStateManager()

        # Services
        self.decomposer = DecompositionService()
        self.prioritizer = TaskPrioritizer()
        self.scheduler = TaskScheduler()
        self.critic = Critic()
        self.evaluator = Evaluator()
        self.validator = PlanValidator()
        self.verifier = Verifier()
        self.reflector = Reflector()
        self.replanner = Replanner()
        self.retry = RetryAnalyzer()

        # Routing
        self.router = Router()
        self.policy = RoutingPolicy()
        self.tools = ToolSelector()
        self.agents = AgentSelector()

        # Execution
        self.task_executor = TaskExecutor(
            task_handler if task_handler is not None else _noop_handler
        )
        self.async_runner = AsyncRunner(
            self.task_executor,
            max_concurrent=max_concurrent,
        )
        self.checkpoints = CheckpointManager()
        self.recovery = RecoveryService(self.checkpoints)

        self.config: dict[str, Any] = dict(config or {})
        self.max_concurrent = max_concurrent

        # Shared lifecycle (deferred import to avoid cycles)
        from .lifecycle import PlanLifecycle

        self.lifecycle = PlanLifecycle(self)

    @property
    def task_handler(self) -> Any:
        """The configured task handler."""
        return self.task_executor.handler

    def snapshot(self) -> dict[str, Any]:
        """Collect a diagnostic snapshot of the context."""
        return {
            "metrics": self.metrics.snapshot(),
            "timeline_entries": len(self.timeline.entries),
            "goals": len(self.goals._goals),  # noqa: SLF001
            "tasks": len(self.tasks._tasks),  # noqa: SLF001
            "max_concurrent": self.max_concurrent,
        }

    def __repr__(self) -> str:
        return (
            "PlanningContext("
            f"goals={len(self.goals._goals)}, "  # noqa: SLF001
            f"tasks={len(self.tasks._tasks)}"  # noqa: SLF001
            ")"
        )
