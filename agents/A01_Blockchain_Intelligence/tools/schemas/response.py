"""
Tools :: Schemas :: Response
============================

Canonical response contract returned by every tool execution.

The Planning Engine and higher layers only ever receive ``ToolResponse``
objects; provider-specific response shapes are normalized by adapters and the
executor before any of those layers sees a result. This keeps a uniform
contract across every transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional


@dataclass
class ResponseMetadata:
    """Timing, identity and accounting info attached to a response."""

    request_id: str = ""
    tool: str = ""
    started_at: str = ""
    duration_ms: float = 0.0
    retries: int = 0
    status: str = "success"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "tool": self.tool,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "retries": self.retries,
            "status": self.status,
        }


@dataclass
class ToolResponse:
    """
    Normalized result of a tool execution.

    ``ok`` is True when the tool produced a payload; False when it produced an
    error. ``data`` holds the payload (dict/list/scalar). ``error`` carries a
    standardized error dict (``code``, ``message``, ...). ``metadata`` keeps
    timing/identity; ``trace`` may hold debug details for the monitoring layer.
    """

    ok: bool = True
    data: Any = None
    error: Optional[Mapping[str, Any]] = None
    warnings: List[Mapping[str, Any]] = field(default_factory=list)
    metadata: ResponseMetadata = field(default_factory=ResponseMetadata)

    @classmethod
    def success(
        cls, data: Any = None, *, tool: str = "", request_id: str = "", duration_ms: float = 0.0
    ) -> "ToolResponse":
        meta = ResponseMetadata(tool=tool, request_id=request_id, duration_ms=duration_ms, status="success")
        return cls(ok=True, data=data, metadata=meta)

    @classmethod
    def failure(
        cls,
        message: str,
        *,
        code: str = "EXECUTION_ERROR",
        tool: str = "",
        request_id: str = "",
        details: Optional[Mapping[str, Any]] = None,
    ) -> "ToolResponse":
        meta = ResponseMetadata(tool=tool, request_id=request_id, status="error")
        err: Dict[str, Any] = {"code": code, "message": message}
        if details:
            err["details"] = details
        return cls(ok=False, error=err, metadata=meta)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": dict(self.error) if self.error else None,
            "warnings": [dict(w) for w in self.warnings],
            "metadata": self.metadata.as_dict(),
        }


def success(data: Any = None, **meta: Any) -> ToolResponse:
    """Shorthand builder for a success response."""
    return ToolResponse.success(data, **meta)


def failure(message: str, **meta: Any) -> ToolResponse:
    """Shorthand builder for a failure response."""
    return ToolResponse.failure(message, **meta)