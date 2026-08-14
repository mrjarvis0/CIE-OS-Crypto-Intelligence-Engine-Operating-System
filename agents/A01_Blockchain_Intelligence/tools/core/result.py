"""
Tools :: Core :: Result
=======================

Standardized tool execution result.

Every tool response flows through the executor which normalizes it into a
:class:`ToolResult`. The Planning Engine never receives provider-specific
shapes; it only sees this contract plus the schema-level ``ToolResponse``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from ..utils.helpers import iso_now
from ..utils.ids import new_id
from ..schemas.response import ToolResponse

__all__ = ["ToolResult", "build_result", "Usage", "TraceInfo"]

@dataclass
class Usage:
    """Accounting counters attached to a result (tokens, cost, calls)."""

    calls: int = 1
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost": self.cost,
        }


@dataclass
class TraceInfo:
    """Tracing hook for the monitoring layer."""

    trace_id: str = ""
    parent_id: str = ""
    spans: List[Dict[str, Any]] = field(default_factory=list)

    def start_span(self, name: str) -> Dict[str, Any]:
        span = {"name": name, "started": time.monotonic(), "duration_ms": 0.0}
        self.spans.append(span)
        return span

    def end_span(self, span: Dict[str, Any]) -> None:
        span["duration_ms"] = (time.monotonic() - span["started"]) * 1000.0

    def as_dict(self) -> Dict[str, Any]:
        return {"trace_id": self.trace_id, "parent_id": self.parent_id, "spans": list(self.spans)}


@dataclass
class ToolResult:
    """Normalized outcome of a tool execution.

    ``ok`` mirrors the response contract; ``data`` is the payload; ``error``
    is a canonical error dict (code + message + recoverable). Metadata always
    carries request_id, tool, duration and usage so telemetry is uniform.
    """

    ok: bool = True
    data: Any = None
    error: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    request_id: str = field(default_factory=lambda: new_id(prefix="req"))
    tool: str = ""
    duration_ms: float = 0.0
    usage: Usage = field(default_factory=Usage)
    trace: TraceInfo = field(default_factory=TraceInfo)
    created_at: str = field(default_factory=iso_now)

    @classmethod
    def from_response(cls, response: ToolResponse, *, tool: str = "") -> "ToolResult":
        """Wrap a schema-level response into a result record."""
        if isinstance(response, ToolResponse):
            return cls(
                ok=response.ok,
                data=response.data,
                error=dict(response.error) if response.error else None,
                request_id=response.metadata.request_id or cls.__new__(cls).request_id,
                tool=response.metadata.tool or tool,
                duration_ms=response.metadata.duration_ms,
            )
        if isinstance(response, Mapping):
            return cls(
                ok=bool(response.get("ok", True)),
                data=response.get("data"),
                error=response.get("error"),
                tool=tool,
            )
        return cls(ok=True, data=response, tool=tool)

    def to_response(self) -> ToolResponse:
        """Rebuild the schema-level response from this result."""
        from ..schemas.response import ResponseMetadata

        return ToolResponse(
            ok=self.ok,
            data=self.data,
            error=dict(self.error) if self.error else None,
            warnings=[
                {"message": w} for w in self.warnings
            ],
            metadata=ResponseMetadata(
                request_id=self.request_id,
                tool=self.tool,
                duration_ms=self.duration_ms,
                status="success" if self.ok else "error",
            ),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "warnings": list(self.warnings),
            "request_id": self.request_id,
            "tool": self.tool,
            "duration_ms": self.duration_ms,
            "usage": self.usage.as_dict(),
            "trace": self.trace.as_dict(),
            "created_at": self.created_at,
        }


def build_result(
    *,
    ok: bool,
    data: Any = None,
    error: Optional[Dict[str, Any]] = None,
    tool: str = "",
    request_id: str = "",
    duration_ms: float = 0.0,
    **extra: Any,
) -> ToolResult:
    """Convenience builder for the executor."""
    return ToolResult(
        ok=ok,
        data=data,
        error=error,
        tool=tool,
        request_id=request_id or new_id(prefix="req"),
        duration_ms=duration_ms,
    )