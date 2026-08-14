"""
Tools :: Core :: Manager
========================

Top-level facade over the whole core runtime.

A manager owns a registry, a permission map and an executor, wires them
together, and offers the high-level operations the calling layer actually
uses: add/remove tools, query the registry, run requests synchronously and
asynchronously, and snapshot health. One manager per runtime process.
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional, Sequence

from ..schemas.request import ToolRequest
from .exceptions import ToolNotFoundError
from .registry import ToolRegistry
from .executor import Executor, ExecutionPolicy
from .permissions import ToolPermissionMap
from .result import ToolResult
from .context import ToolContext, new_context

__all__ = ["ToolManager"]


class ToolManager:
    """Facade bundling registry + permissions + executor."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        *,
        permissions: Optional[ToolPermissionMap] = None,
        policy: Optional[ExecutionPolicy] = None,
        name: str = "tool-manager",
    ) -> None:
        self.name = name
        self.registry = registry or ToolRegistry()
        self.permissions = permissions or ToolPermissionMap()
        self.executor = Executor(self.registry, policy=policy, permissions=self.permissions)

    # -- registration ------------------------------------------------------ #

    def add(self, tool: Any, *, enabled: bool = True) -> None:
        """Register a tool instance."""
        self.registry.register(tool, enabled=enabled)

    def remove(self, name: str) -> bool:
        """Unregister a tool; returns True when it existed."""
        return self.registry.unregister(name)

    def enable(self, name: str) -> None:
        self.registry.enable(name)

    def disable(self, name: str) -> None:
        self.registry.disable(name)

    # -- lookup ------------------------------------------------------------ #

    def get(self, name: str, *, strict: bool = False) -> Optional[Any]:
        return self.registry.get(name, strict=strict)

    def names(self) -> Sequence[str]:
        return self.registry.names()

    def list(self) -> Sequence[Any]:
        return self.registry.list()

    def search(self, *, capability: str = "", name: str = "") -> Sequence[str]:
        return self.registry.search(capability=capability, name=name)

    def state(self, name: str) -> str:
        return self.registry.state(name)

    def capabilities(self, name: str) -> Sequence[str]:
        return self.registry.capabilities(name)

    # -- execution ---------------------------------------------------------- #

    def run(self, tool: str, **arguments: Any) -> ToolResult:
        """Synchronous execution returning a :class:`ToolResult`."""
        return self.executor.run(tool, **arguments)

    async def arun(self, tool: str, **arguments: Any) -> ToolResult:
        """Async execution returning a :class:`ToolResult`."""
        request = ToolRequest(tool=tool, arguments=arguments)
        return await self.executor.execute(request)

    def grant(self, principal: str, action: str, scope: str = "*") -> None:
        """Grant a permission through the shared map."""
        self.permissions.grant(principal, action, scope)

    # -- health ------------------------------------------------------------- #

    def health(self) -> Mapping[str, Any]:
        """Snapshot of registry + executor state."""
        return {
            "manager": self.name,
            "tools": self.registry.stats().as_dict(),
            "cache_enabled": self.executor.cache.enabled,
            "default_timeout": self.executor.policy.default_timeout,
        }