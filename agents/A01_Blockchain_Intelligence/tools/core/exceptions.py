"""
Tools :: Core :: Exceptions
===========================

Unified exception hierarchy for the Tools subsystem's core kernel.

Every adapter-specific error is translated to a core error here, so the
Planning Engine, Executor and Routing layers never depend on transport
details. Hierarchy:

    ToolError
    ├── ToolNotFoundError          registry lookup missed
    ├── ToolNotEnabledError        tool disabled in lifecycle
    ├── PermissionDeniedError      governance/security rejected
    ├── ValidationError            request failed schema validation
    ├── ExecutionError              tool ran but failed
    ├── DependencyError             dependency missing/incompatible
    ├── VersionError                version conflict
    ├── TimeoutError                execution exceeded budget
    ├── ConfigurationError          misconfigured tool/manager
    ├── TransportError              transport-level failure
    └── LifecycleError              invalid state transition
"""

from __future__ import annotations

__all__ = [
    "ToolError",
    "ToolNotFoundError",
    "ToolNotEnabledError",
    "PermissionDeniedError",
    "ValidationError",
    "ExecutionError",
    "DependencyError",
    "VersionError",
    "TimeoutError",
    "ConfigurationError",
    "TransportError",
    "LifecycleError",
    "CircuitOpenError",
]


class ToolError(Exception):
    """Base class for every core-kernel error."""

    code = "TOOL_ERROR"

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class ToolNotFoundError(ToolError):
    """The requested tool is not present in the registry."""

    code = "TOOL_NOT_FOUND"


class ToolNotEnabledError(ToolError):
    """The tool exists but is currently disabled in its lifecycle."""

    code = "TOOL_NOT_ENABLED"


class PermissionDeniedError(ToolError):
    """The principal lacks the permission required by the tool."""

    code = "PERMISSION_DENIED"


class ValidationError(ToolError):
    """The request failed schema or argument validation."""

    code = "VALIDATION_ERROR"


class ExecutionError(ToolError):
    """The tool executed but the operation itself failed."""

    code = "EXECUTION_ERROR"


class DependencyError(ToolError):
    """A declared dependency is missing or incompatible."""

    code = "DEPENDENCY_ERROR"


class VersionError(ToolError):
    """A version constraint could not be satisfied."""

    code = "VERSION_ERROR"


class TimeoutError(ToolError):
    """Execution exceeded the configured time budget."""

    code = "TIMEOUT_ERROR"


class ConfigurationError(ToolError):
    """The manager or a tool is misconfigured."""

    code = "CONFIGURATION_ERROR"


class TransportError(ToolError):
    """A transport failure surfaced from an adapter."""

    code = "TRANSPORT_ERROR"


class LifecycleError(ToolError):
    """An illegal lifecycle transition was requested."""

    code = "LIFECYCLE_ERROR"


class CircuitOpenError(ToolError):
    """A circuit breaker is open and execution was refused."""

    code = "CIRCUIT_OPEN"