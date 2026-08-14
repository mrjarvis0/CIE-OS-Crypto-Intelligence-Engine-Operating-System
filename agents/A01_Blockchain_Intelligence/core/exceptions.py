"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    core.exceptions

Purpose:
    Exception hierarchy for the Core execution engine.

Every core failure derives from :class:`AgentError`, so callers can catch the
whole family with a single ``except AgentError``.

Security note
-------------
``details`` is intended for operator-facing diagnostics and may end up in logs
or API responses. Do not place secrets, API keys, raw RPC URLs with embedded
credentials, or full request bodies in it.
"""

from __future__ import annotations

from typing import Any


class AgentError(Exception):
    """Base class for every Core error."""

    def __init__(
        self,
        message: str = "Agent error",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)

        self.message = message
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Serializable representation, safe for logs and API responses."""
        return {
            "error": type(self).__name__,
            "message": self.message,
            "details": self.details,
        }

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.message!r})"


class AgentInitializationError(AgentError):
    """Raised when an agent or runtime fails to initialize."""


class AgentRuntimeError(AgentError):
    """Raised on failures during agent execution."""


class ContextError(AgentError):
    """Raised on invalid, missing, or inactive execution context."""


class GuardrailError(AgentError):
    """Raised when a guardrail or policy check rejects an operation."""


class ToolExecutionError(AgentError):
    """Raised when a tool invoked by the agent fails."""

    def __init__(
        self,
        message: str = "Tool execution failed",
        *,
        tool_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)

        self.tool_name = tool_name

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["tool_name"] = self.tool_name
        return payload


class LifecycleError(AgentError):
    """Raised on an illegal agent lifecycle state transition."""

    def __init__(
        self,
        message: str = "Invalid lifecycle transition",
        *,
        current: str | None = None,
        target: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)

        self.current = current
        self.target = target

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["current"] = self.current
        payload["target"] = self.target
        return payload


# =============================================================================
# Data pipeline
# =============================================================================
#
# When these are raised, and when they are not
# --------------------------------------------
# The capture path deliberately does not raise for expected failures. A dead
# provider, a throttled endpoint, and a chain with no archive access are all
# ordinary conditions, and :class:`blockchain.rpc.clients.dispatch.CallResult`
# reports them as data so a caller can tell "the answer is empty" apart from
# "I could not ask". Converting those into exceptions would erase exactly that
# distinction, because a raised error looks identical to a bug.
#
# The exceptions below therefore cover only two situations:
#
#   1. The caller asked for something incoherent -- an unregistered chain, a
#      malformed block payload, an unreadable checkpoint. These are defects.
#   2. The chain said something that must stop the pipeline rather than be
#      absorbed into it. :class:`FinalityViolationError` is the whole reason
#      this group exists.


class PipelineError(AgentError):
    """Base class for failures in the capture-to-storage path."""


class SensorError(PipelineError):
    """Raised when a sensor cannot be constructed or is asked for nonsense."""

    def __init__(
        self,
        message: str = "Sensor failure",
        *,
        sensor: str | None = None,
        chain: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)

        self.sensor = sensor
        self.chain = chain

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["sensor"] = self.sensor
        payload["chain"] = self.chain
        return payload


class IngestionError(PipelineError):
    """Raised on an unrecoverable fault in the ingestion loop."""


class CheckpointError(IngestionError):
    """
    Raised when a checkpoint cannot be read, written, or trusted.

    Losing a checkpoint is recoverable -- ingestion restarts from a configured
    height. Silently accepting a corrupt one is not: it would resume from a
    position that never happened and leave an unnoticed hole in history.
    """


class FinalityViolationError(IngestionError):
    """
    Raised when a reorg reaches below a height already observed as finalized.

    On a deterministic chain this cannot legitimately occur, so it is not a
    deep reorg to absorb. It means a provider is serving a different network,
    a fork client is out of consensus, or an endpoint is lying. Rolling back
    finalized history on that basis would let one bad endpoint rewrite A01's
    record, so the loop stops and a human decides.
    """

    def __init__(
        self,
        message: str = "Reorg crossed finality",
        *,
        chain: str | None = None,
        depth: int | None = None,
        finalized_height: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)

        self.chain = chain
        self.depth = depth
        self.finalized_height = finalized_height

    def to_dict(self) -> dict[str, Any]:
        payload = super().to_dict()
        payload["chain"] = self.chain
        payload["depth"] = self.depth
        payload["finalized_height"] = self.finalized_height
        return payload


__all__ = [
    "AgentError",
    "AgentInitializationError",
    "AgentRuntimeError",
    "CheckpointError",
    "ContextError",
    "FinalityViolationError",
    "GuardrailError",
    "IngestionError",
    "LifecycleError",
    "PipelineError",
    "SensorError",
    "ToolExecutionError",
]
