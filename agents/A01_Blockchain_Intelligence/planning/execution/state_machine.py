"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.execution.state_machine

Purpose:
    Execution state machine for the planning subsystem.

Defines the allowed lifecycle transitions for task execution and
enforces them when status changes are recorded.
"""

from __future__ import annotations

import logging
from typing import Any

from planning.schemas import ExecutionSchema
from planning.utils.constants import ExecutionStatus

logger = logging.getLogger("a01.planning.execution")


class StateMachineError(Exception):
    """
    Base class for execution state machine failures.
    """


class InvalidExecutionTransitionError(StateMachineError):
    """
    Raised when an execution status transition is not allowed.
    """


# Allowed execution status transitions.
_EXECUTION_TRANSITIONS: dict[ExecutionStatus, set[ExecutionStatus]] = {
    ExecutionStatus.CREATED: {
        ExecutionStatus.SCHEDULED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.SCHEDULED: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.RUNNING: {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.RETRYING,
        ExecutionStatus.INTERRUPTED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.RETRYING: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.INTERRUPTED: {
        ExecutionStatus.RECOVERED,
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    },
    ExecutionStatus.RECOVERED: {
        ExecutionStatus.RUNNING,
        ExecutionStatus.CANCELLED,
    },
    ExecutionStatus.SUCCEEDED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.CANCELLED: set(),
}


class ExecutionStateMachine:
    """
    Enforces the execution lifecycle of an ``ExecutionSchema``.

    Responsibilities:
        * Transition validation
        * Status mutation with timestamp updates
    """

    @staticmethod
    def is_valid_transition(
        current: ExecutionStatus,
        target: ExecutionStatus,
    ) -> bool:
        """Whether a transition is allowed by the state table."""
        if current == target:
            return True
        return target in _EXECUTION_TRANSITIONS.get(current, set())

    @staticmethod
    def transition(
        execution: ExecutionSchema,
        status: ExecutionStatus,
    ) -> ExecutionSchema:
        """
        Transition an execution record to a new status.

        Raises
        ------
        InvalidExecutionTransitionError
            When the transition is not allowed.
        """

        if status == execution.status:
            return execution

        if not ExecutionStateMachine.is_valid_transition(
            execution.status,
            status,
        ):
            raise InvalidExecutionTransitionError(
                f"invalid execution transition: "
                f"{execution.status.value} -> {status.value}"
            )

        execution.status = status
        execution.touch()
        execution.validate()
        logger.info(
            "execution %s transitioned: %s",
            execution.id,
            status.value,
        )
        return execution

    @staticmethod
    def mark_succeeded(execution: ExecutionSchema, result: Any = None) -> ExecutionSchema:
        """Transition to SUCCEEDED, attaching a result."""
        if result is not None:
            execution.result = result
        return ExecutionStateMachine.transition(
            execution,
            ExecutionStatus.SUCCEEDED,
        )

    @staticmethod
    def mark_failed(
        execution: ExecutionSchema,
        error: str | None = None,
    ) -> ExecutionSchema:
        """Transition to FAILED, attaching an error message."""
        if error is not None:
            execution.error = error
        return ExecutionStateMachine.transition(
            execution,
            ExecutionStatus.FAILED,
        )

    @staticmethod
    def mark_retrying(execution: ExecutionSchema) -> ExecutionSchema:
        """Transition to RETRYING."""
        return ExecutionStateMachine.transition(
            execution,
            ExecutionStatus.RETRYING,
        )

    @staticmethod
    def mark_interrupted(execution: ExecutionSchema) -> ExecutionSchema:
        """Transition to INTERRUPTED."""
        return ExecutionStateMachine.transition(
            execution,
            ExecutionStatus.INTERRUPTED,
        )
