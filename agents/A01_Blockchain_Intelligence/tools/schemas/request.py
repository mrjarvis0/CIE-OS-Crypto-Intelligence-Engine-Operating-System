"""
Tools :: Schemas :: Request
===========================

Canonical request contracts for the Tools subsystem.

Every request -- whether produced by the Planning Engine, the Discovery layer,
or the Executor -- is described by one of these structures. The schemas stay
transport-agnostic: adapters translate the normalized request into protocol
specific wire formats, never the reverse.

``ToolRequest`` is the primary contract; the context fields (request_id,
session_id, user) are filled by the manager from the execution context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from ..utils.ids import new_id

__all__ = ["ToolRequest", "RequestContext", "new_request"]


@dataclass(frozen=True)
class RequestContext:
    """
    Immutable envelope of caller identity and provenance for a request.

    ``user`` is the human or service principal; ``session`` groups related
    requests; ``trace_id`` correlates distributed spans. Fields are free-form
    so consumers can attach their own keys (``org``, ``env`` ...) via
    ``attributes``.
    """

    request_id: str = field(default_factory=lambda: new_id(prefix="req"))
    user: str = ""
    session_id: str = ""
    trace_id: str = ""
    source: str = "planner"
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def with_fields(self, **overrides: Any) -> "RequestContext":
        return RequestContext(
            request_id=overrides.get("request_id", self.request_id),
            user=overrides.get("user", self.user),
            session_id=overrides.get("session_id", self.session_id),
            trace_id=overrides.get("trace_id", self.trace_id),
            source=overrides.get("source", self.source),
            attributes={**self.attributes, **overrides.get("attributes", {})},
        )


@dataclass(frozen=True)
class ToolRequest:
    """
    The normalized request handed to the Executor.

    Fields
    ------
    tool:
        Registered tool name (optionally ``namespace:name``).
    arguments:
        Input values bound to the tool's declared parameters.
    timeout:
        Execution time budget in seconds.
    retries:
        Extra attempts allowed on retryable failures.
    context:
        Provenance envelope (request/session/trace ids).
    raw:
        Optional original request payload preserved for audit trails.
    """

    tool: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    timeout: float = 30.0
    retries: int = 0
    context: RequestContext = field(default_factory=RequestContext)
    raw: Optional[Any] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool:
            raise ValueError("tool name is required")
        if self.timeout <= 0:
            raise ValueError("timeout must be > 0")

    def get(self, key: str, default: Any = None) -> Any:
        """Argument lookup with default."""
        return self.arguments.get(key, default)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "timeout": self.timeout,
            "retries": self.retries,
            "context": {
                "request_id": self.context.request_id,
                "user": self.context.user,
                "session_id": self.context.session_id,
                "trace_id": self.context.trace_id,
                "source": self.context.source,
                "attributes": dict(self.context.attributes),
            },
            "metadata": dict(self.metadata),
        }


def new_request(tool: str, **arguments: Any) -> ToolRequest:
    """Factory producing a fresh :class:`ToolRequest` with defaults."""
    return ToolRequest(tool=tool, arguments=arguments)