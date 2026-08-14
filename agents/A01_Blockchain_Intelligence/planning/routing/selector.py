"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.routing.selector

Purpose:
    Tool and agent selection for the planning subsystem.

Specializes routing for tool and agent targets: registers targets,
selects a target for a task, and reports the decision.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from planning.schemas import TaskSchema
from planning.utils.constants import RoutingStrategy

from .router import Router
from .strategy import RouteResult

logger = logging.getLogger("a01.planning.routing")


class Tool(Protocol):
    """
    Protocol implemented by routable tools.

    A tool exposes an id, a description, and an invocation method.
    """

    id: str
    description: str

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ...


class Agent(Protocol):
    """
    Protocol implemented by routable agents.

    An agent exposes an id and a description of its capabilities.
    """

    id: str
    description: str


class _TargetSelector:
    """Shared registration and selection logic for routable targets."""

    def __init__(self, strategy: RoutingStrategy) -> None:
        self._router = Router(strategy=strategy)

    @property
    def router(self) -> Router:
        """The underlying router instance."""
        return self._router

    def register(self, target: Any) -> None:
        """Register a target for selection."""
        self._router.register(target)

    def register_many(self, targets: list[Any]) -> None:
        """Register multiple targets."""
        self._router.register_many(targets)

    def unregister(self, target_id: str) -> None:
        """Remove a registered target."""
        self._router.unregister(target_id)

    def select(
        self,
        task: TaskSchema,
        *,
        strict: bool = False,
    ) -> RouteResult:
        """
        Select a target for a task.

        Raises
        ------
        NoRouteFoundError
            When no target qualifies and ``strict`` is true.
        """

        return self._router.route(task, strict=strict)

    def get(self, target_id: str) -> Any:
        """Return a registered target by id."""
        return self._router.targets[target_id]

    def list(self) -> list[Any]:
        """Return all registered targets."""
        return list(self._router.targets.values())


class ToolSelector(_TargetSelector):
    """
    Routes tasks to registered tools.

    Responsibilities:
        * Tool registration
        * Tool selection per task
        * Tool lookup by id
    """

    def __init__(self, router: Router | None = None) -> None:
        super().__init__(RoutingStrategy.BEST_SCORE)
        if router is not None:
            self._router = router

    def register(self, tool: Tool) -> None:
        """Register a tool for selection."""
        super().register(tool)

    def register_many(self, tools: list[Tool]) -> None:
        """Register multiple tools."""
        super().register_many(tools)

    def unregister(self, tool_id: str) -> None:
        """Remove a registered tool."""
        super().unregister(tool_id)

    def get(self, tool_id: str) -> Tool:
        """Return a registered tool by id."""
        return self._router.targets[tool_id]

    def list(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._router.targets.values())


class AgentSelector(_TargetSelector):
    """
    Routes tasks to registered agents.

    Responsibilities:
        * Agent registration
        * Agent selection per task
        * Agent lookup by id
    """

    def __init__(self, router: Router | None = None) -> None:
        super().__init__(RoutingStrategy.BEST_SCORE)
        if router is not None:
            self._router = router

    def register(self, agent: Agent) -> None:
        """Register an agent for selection."""
        super().register(agent)

    def register_many(self, agents: list[Agent]) -> None:
        """Register multiple agents."""
        super().register_many(agents)

    def unregister(self, agent_id: str) -> None:
        """Remove a registered agent."""
        super().unregister(agent_id)

    def get(self, agent_id: str) -> Agent:
        """Return a registered agent by id."""
        return self._router.targets[agent_id]

    def list(self) -> list[Agent]:
        """Return all registered agents."""
        return list(self._router.targets.values())
