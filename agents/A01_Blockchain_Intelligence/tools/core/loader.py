"""
Tools :: Core :: Loader
=======================

Handles creating tools from declarative descriptions and enriching the
registry.

The loader compiles schema/manifest directives into concrete tool instances
(thin wrappers whose ``run`` body is an injectable callable) and registers
them, so a registry can be populated entirely from plain data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

from ..schemas.tool import ToolSchema
from ..schemas.metadata import ToolMetadata
from .tool import Tool, ToolConfig
from .manifest import Manifest, ManifestItem
from .registry import ToolRegistry
from .exceptions import ToolError, DependencyError

__all__ = ["ToolLoader", "CallableTool", "LoadedTool"]


class CallableTool(Tool):
    """Concrete :class:`Tool` wrapping a plain ``fn(**kwargs)``."""

    def __init__(
        self,
        *,
        name: str,
        description: str = "",
        fn: Callable[..., Any],
        schema: Optional[ToolSchema] = None,
        capabilities: Sequence[str] = (),
        config: Optional[Mapping[str, Any]] = None,
        **extra: Any,
    ) -> None:
        self._fn = fn
        self.capabilities = tuple(capabilities)
        super().__init__(
            name=name,
            description=description,
            config=config,
            schema=None,
        )
        self.schema = schema

    def run(self, **arguments: Any) -> Any:
        return self._fn(**arguments)


LoadedTool = Mapping[str, Any]
"""A loaded tool snapshot: name plus its (optional) schema."""

Loaded = LoadedTool


@dataclass
class ToolLoader:
    """Populate a :class:`ToolRegistry` from manifest+schemas."""

    registry: ToolRegistry
    resolver: Optional[Callable[[str, Any], Any]] = None

    def load_callable(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        description: str = "",
        capabilities: Sequence[str] = (),
        parameters: Optional[Sequence[Mapping[str, Any]]] = None,
        config: Optional[Mapping[str, Any]] = None,
        enabled: bool = True,
    ) -> CallableTool:
        """Wrap a callable and (optionally) register it."""
        schema = None
        if parameters:
            schema = ToolSchema.build(
                name=name,
                parameters=parameters,
                description=description,
            )
        tool = CallableTool(
            name=name,
            description=description,
            fn=fn,
            schema=schema,
            capabilities=capabilities,
            config=config,
        )
        if self.registry is not None:
            self.registry.register(tool, enabled=enabled)
        return tool

    def apply_manifest(self, manifest: Manifest) -> Sequence[str]:
        """Load every manifest item whose tool name resolves, in dependency order."""
        loaded: list[str] = []
        for item in manifest.items:
            if not item.enable:
                continue
            if self.resolver is None:
                raise DependencyError(
                    f"no resolver configured to materialize manifest item {item.name!r}"
                )
            tool = self.resolver(item.name, item)
            tool.name = item.name
            if self.registry is not None:
                self.registry.register(tool)
            loaded.append(item.name)
        return loaded

    def entries(self, registry: Optional[ToolRegistry] = None) -> Sequence[Loaded]:
        """Snapshot all registered tools as plain dicts."""
        reg = registry or self.registry
        if reg is None:
            return ()
        return [
            {"name": name, "schema": getattr(reg.get(name), "schema", None)}
            for name in reg.names()
        ]