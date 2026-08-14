"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.tasks.workflow

Purpose:
    Workflow definitions for the planning subsystem.

A workflow is a reusable template of tasks and dependencies that can
be instantiated for a goal, producing a validated task graph.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from planning.schemas import GoalSchema, TaskSchema
from planning.schemas.base import SchemaValidationError
from planning.utils.constants import Priority
from planning.utils.ids import generate_workflow_id

from .decomposition import verify_task_connectivity
from .task_graph import TaskGraph

logger = logging.getLogger("a01.planning.tasks")


class WorkflowError(Exception):
    """
    Base class for workflow failures.
    """


class WorkflowNotFoundError(WorkflowError):
    """
    Raised when a workflow does not exist.
    """


@dataclass(slots=True)
class WorkflowStep:
    """
    A named step in a workflow template.

    Fields:
        * Step name and description
        * Default tool and priority
        * Dependency step names
    """

    name: str
    description: str = ""
    tool: str | None = None
    priority: Priority = Priority.NORMAL
    dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowDefinition:
    """
    Reusable task pipeline template.

    Fields:
        * Identifier, name, and description
        * Ordered steps
        * Version
    """

    name: str
    steps: list[WorkflowStep] = field(default_factory=list)
    description: str = ""
    id: str = field(default_factory=generate_workflow_id)
    version: str = "1"

    def validate(self) -> None:
        """Validate the workflow template."""
        if not self.name or not self.name.strip():
            raise SchemaValidationError("workflow.name must be non-empty.")

        if not self.id or not self.id.strip():
            raise SchemaValidationError("workflow.id must be non-empty.")

        names = {step.name for step in self.steps}

        if len(names) != len(self.steps):
            raise SchemaValidationError("workflow steps must have unique names.")

        for step in self.steps:
            for dependency in step.dependencies:
                if dependency not in names:
                    raise SchemaValidationError(
                        f"step {step.name!r} depends on unknown step {dependency!r}"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "steps": [
                {
                    "name": step.name,
                    "description": step.description,
                    "tool": step.tool,
                    "priority": step.priority.value,
                    "dependencies": list(step.dependencies),
                }
                for step in self.steps
            ],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowDefinition":
        try:
            workflow = cls(
                name=str(payload["name"]),
                description=str(payload.get("description", "")),
                id=str(payload.get("id", generate_workflow_id())),
                version=str(payload.get("version", "1")),
                steps=[
                    WorkflowStep(
                        name=str(step["name"]),
                        description=str(step.get("description", "")),
                        tool=step.get("tool"),
                        priority=Priority(
                            int(step.get("priority", Priority.NORMAL.value))
                        ),
                        dependencies=list(step.get("dependencies", [])),
                    )
                    for step in payload.get("steps", [])
                ],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SchemaValidationError(f"invalid workflow payload: {exc}") from exc
        workflow.validate()
        return workflow

    def __repr__(self) -> str:
        return f"WorkflowDefinition(id={self.id!r}, steps={len(self.steps)})"


class WorkflowRegistry:
    """
    In-memory registry of reusable workflows.

    Responsibilities:
        * Workflow registration and lookup
        * Template instantiation into task graphs
    """

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._lock = asyncio.Lock()

    @property
    def workflows(self) -> dict[str, WorkflowDefinition]:
        """Read-only view of registered workflows."""
        return dict(self._workflows)

    async def register(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        """Register a workflow template."""
        workflow.validate()

        async with self._lock:
            self._workflows[workflow.id] = workflow

        logger.info("workflow registered: %s", workflow.id)
        return workflow

    async def get(self, workflow_id: str) -> WorkflowDefinition:
        """Return a workflow by id."""
        workflow = self._workflows.get(workflow_id)

        if workflow is None:
            raise WorkflowNotFoundError(f"workflow not found: {workflow_id}")

        return workflow

    async def list(self) -> list[WorkflowDefinition]:
        """Return all registered workflows."""
        return list(self._workflows.values())

    async def instantiate(
        self,
        workflow_id: str,
        goal: GoalSchema,
        *,
        plan_id: str | None = None,
        inputs: Mapping[str, Any] | None = None,
    ) -> TaskGraph:
        """
        Instantiate a workflow template into a validated task graph.

        Parameters
        ----------
        inputs
            Optional mapping of step name to input data attached to the
            generated task.

        Raises
        ------
        WorkflowNotFoundError
            When the workflow does not exist.
        CyclicDependencyError
            When the instantiated tasks form a cycle.
        """

        workflow = await self.get(workflow_id)
        step_index = {step.name: step for step in workflow.steps}
        task_by_step: dict[str, TaskSchema] = {}
        tasks: list[TaskSchema] = []

        for step in workflow.steps:
            task = TaskSchema(
                name=step.name,
                description=step.description,
                plan_id=plan_id,
                goal_id=goal.id,
                dependencies=[task_by_step[d].id for d in step.dependencies],
                priority=step.priority,
                tool=step.tool,
                input_data=inputs.get(step.name) if inputs else None,
            )
            task.validate()
            task_by_step[step.name] = task
            tasks.append(task)

        verify_task_connectivity(tasks, {task.id for task in tasks})

        graph = TaskGraph(tasks)
        graph.validate_dag()
        logger.info(
            "workflow %s instantiated for goal %s: %d tasks",
            workflow_id,
            goal.id,
            len(tasks),
        )
        return graph
