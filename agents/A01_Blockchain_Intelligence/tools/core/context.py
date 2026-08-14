"""
Tools :: Core :: Context
========================

Structured execution context passed to every tool run.

Every tool receives the same shape of context: identity of the caller,
request provenance, session, memory reference, security decision and runtime
configuration. Tools should never construct their own ad-hoc context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from ..utils.ids import new_id, new_trace_id
from ..schemas.request import RequestContext

__all__ = ["ToolContext", "new_context"]


@dataclass
class ToolContext:
    """
    Immutable-by-convention envelope for one tool execution.

    Fields beyond identity are free-form so the Planning/Memory layers can
    attach their own keys without breaking the contract.
    """

    request_id: str = field(default_factory=lambda: new_id(prefix="req"))
    trace_id: str = field(default_factory=new_trace_id)
    user_id: str = ""
    session_id: str = ""
    tool: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    permissions: Mapping[str, Any] = field(default_factory=dict)
    runtime: Mapping[str, Any] = field(default_factory=dict)
    memory_refs: list = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def with_tool(self, tool: str, **arguments: Any) -> "ToolContext":
        """Return a derived context bound to a concrete tool."""
        return ToolContext(
            request_id=self.request_id,
            trace_id=self.trace_id,
            user_id=self.user_id,
            session_id=self.session_id,
            tool=tool,
            arguments=dict(arguments) or dict(self.arguments),
            permissions=dict(self.permissions),
            runtime=dict(self.runtime),
            memory_refs=list(self.memory_refs),
            attributes=dict(self.attributes),
        )

    def to_request_context(self) -> RequestContext:
        """Emit the schema-level provenance envelope."""
        return RequestContext(
            request_id=self.request_id,
            user=self.user_id,
            session_id=self.session_id,
            trace_id=self.trace_id,
            source="executor",
            attributes=dict(self.attributes),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "permissions": dict(self.permissions),
            "runtime": dict(self.runtime),
            "memory_refs": list(self.memory_refs),
            "attributes": dict(self.attributes),
        }


def new_context(**overrides: Any) -> ToolContext:
    """Factory creating a fresh execution context."""
    return ToolContext(**overrides)