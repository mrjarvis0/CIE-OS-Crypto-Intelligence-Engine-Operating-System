"""
Tools :: Core :: Executor
=========================

Dispatches tool executions with permission, lifecycle and cache checks.

A single choke point between the registry and the calling layer (planner,
tool or router). It validates the tool exists and is enabled, checks the
principal's permissions, runs within a per-request timeout, records
duration, and returns a :class:`ToolResult` on every path (no raw raises
leak out of an execution).
"""

from __future__ import annotations

import asyncio
import functools
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from ..schemas.request import ToolRequest
from .exceptions import ExecutionError, TimeoutError, PermissionDeniedError, ToolNotEnabledError, ToolNotFoundError
from ..utils.helpers import elapsed_ms
from .registry import ToolRegistry
from .context import ToolContext, new_context
from .result import ToolResult, build_result
from .cache import ExecutionCache
from .permissions import ToolPermissionMap

__all__ = ["Executor", "ExecutionPolicy"]


@dataclass
class ExecutionPolicy:
    """Runtime knobs for a single executor."""

    default_timeout: float = 30.0
    cache: bool = True
    cache_ttl: float = 30.0
    cache_scope: str = ""
    principal: str = "system"


class Executor:
    """Authoritative dispatcher over a :class:`ToolRegistry`."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        policy: Optional[ExecutionPolicy] = None,
        permissions: Optional[ToolPermissionMap] = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or ExecutionPolicy()
        self.permissions = permissions or ToolPermissionMap()
        self.cache = ExecutionCache(ttl=self.policy.cache_ttl, enabled=self.policy.cache)

    # -- execution --------------------------------------------------------- #

    async def execute(
        self,
        request: ToolRequest,
        *,
        context: Optional[ToolContext] = None,
        timeout: Optional[float] = None,
        principal: str = "",
    ) -> ToolResult:
        """Authorized, timed, cached dispatch of one tool request."""
        ctx = context or new_context(tool=request.tool)
        principal = principal or ctx.attributes.get("principal") or self.policy.principal
        limit = timeout or self.policy.default_timeout

        denied = self.permissions_check(principal, request.tool)
        if denied:
            return build_result(
                ok=False,
                error={"code": "PERMISSION_DENIED", "message": denied},
                tool=request.tool,
                request_id=ctx.request_id,
            )

        started = time.monotonic()

        async def _dispatch() -> ToolResult:
            try:
                tool = self.registry.require(request.tool)
            except ToolNotFoundError as exc:
                return build_result(ok=False, error={"code": "TOOL_NOT_FOUND", "message": str(exc)}, tool=request.tool, request_id=ctx.request_id)
            except ToolNotEnabledError as exc:
                return build_result(ok=False, error={"code": "TOOL_NOT_ENABLED", "message": str(exc)}, tool=request.tool, request_id=ctx.request_id)

            try:
                if not tool.initialized:
                    tool.prepare()
                coro = asyncio.to_thread(functools.partial(tool.run, **request.arguments))
                payload = await asyncio.wait_for(coro, timeout=limit) if limit > 0 else await coro
                return build_result(
                    ok=True,
                    data=payload,
                    tool=request.tool,
                    request_id=ctx.request_id,
                    duration_ms=elapsed_ms(started),
                )
            except asyncio.TimeoutError:
                return build_result(
                    ok=False,
                    error={"code": "TIMEOUT", "message": f"tool {request.tool!r} exceeded {limit}s"},
                    tool=request.tool,
                    request_id=ctx.request_id,
                    duration_ms=elapsed_ms(started),
                )
            except Exception as exc:
                return build_result(
                    ok=False,
                    error={"code": "EXECUTION_ERROR", "message": str(exc)},
                    tool=request.tool,
                    request_id=ctx.request_id,
                    duration_ms=elapsed_ms(started),
                )

        if not self.policy.cache:
            return await _dispatch()

        cached = self.cache.get(request.tool, request.arguments, scope=self.policy.cache_scope)
        if cached is not None:
            return cached
        result = await _dispatch()
        if result.ok:
            self.cache.set(request.tool, request.arguments, result, scope=self.policy.cache_scope)
        return result

    # -- auth -------------------------------------------------------------- #

    def permissions_check(self, principal: str, tool: str) -> Optional[str]:
        """Return human-readable denial reason, or ``None`` when allowed."""
        if not self.permissions.allows(principal, "execute", tool):
            return f"principal {principal!r} lacks permission execute:{tool}"
        return None

    def authorize(self, principal: str, tool: str) -> None:
        reason = self.permissions_check(principal, tool)
        if reason:
            raise PermissionDeniedError(reason)

    # -- sync convenience -------------------------------------------------- #

    def run(self, tool: str, **arguments: Any) -> ToolResult:
        """Synchronous convenience wrapper around :meth:`execute`."""
        req = ToolRequest(tool=tool, arguments=arguments)
        return asyncio.new_event_loop().run_until_complete(self.execute(req))