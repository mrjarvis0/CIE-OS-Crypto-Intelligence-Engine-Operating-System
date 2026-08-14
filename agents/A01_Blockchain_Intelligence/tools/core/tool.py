"""
Tools :: Core :: Tool
=====================

The base Tool abstraction every tool in the platform implements.

Tools are protocol-independent: they define identity, configuration, lifecycle
hooks and a ``run``/``arun`` execution contract. Concrete implementations
(which may wrap adapters, Python callables, MCP servers, or CLI processes)
inject their transport through the registry.

No business logic lives here; this is pure kernel contract.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, Dict, Mapping, Optional

from ..schemas.tool import ToolSchema
from .exceptions import ToolError

__all__ = ["Tool", "ToolConfig", "AbstractTool"]


class ToolConfig:
    """
    Mutable holder for a tool's runtime configuration.

    Values are dict-like and stored normalized; ``__getitem__`` raises
    :class:`KeyError` semantics but attribute-style access is also provided
    for ergonomics.
    """

    def __init__(self, values: Optional[Mapping[str, Any]] = None) -> None:
        self._values: Dict[str, Any] = dict(values or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._values)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._values[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self._values


class Tool(metaclass=abc.ABCMeta):
    """
    Abstract base for every tool in the registry.

    Subclasses must implement :meth:`run`. Optional :meth:`arun` defaults to
    running ``run`` in a worker thread (safe for CPU/OIO-bound tools).

    Lifecycle hooks (``prepare``/``teardown``) are invoked by the executor.
    ``validate()`` should raise :class:`ToolError` when misconfigured.
    """

    #: stable identifier; subclasses must set or pass it in __init__.
    name: str = ""

    #: tool schema describing the public contract.
    schema: Optional[ToolSchema] = None

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        description: str = "",
        config: Optional[Mapping[str, Any]] = None,
        logger: Optional[logging.Logger] = None,
        **extra: Any,
    ) -> None:
        self.name = name or self.name
        if not self.name:
            raise ToolError("tool name is required (set class attribute or __init__)")
        self.description = description
        self.config = ToolConfig(config)
        self.extra = dict(extra)
        self.log = logger or logging.getLogger(f"tools.core.tool.{self.name}")
        self._initialized = False

    # -- lifecycle --------------------------------------------------------- #

    def prepare(self) -> None:
        """Called by the executor before the first run (may set up resources)."""
        self._initialized = True

    def teardown(self) -> None:
        """Release resources acquired during the lifecycle."""
        self._initialized = False

    @property
    def initialized(self) -> bool:
        return self._initialized

    # -- contract ---------------------------------------------------------- #

    def validate(self) -> None:
        """Config sanity check; raises :class:`ToolError` on failure."""
        if not self.name:
            raise ToolError("tool has no name")

    @abc.abstractmethod
    def run(self, **arguments: Any) -> Any:
        """Execute the tool with keyword arguments and return a payload."""
        raise NotImplementedError

    async def arun(self, **arguments: Any) -> Any:
        """Async execution hook; default runs :meth:`run` in a worker thread."""
        import asyncio
        import functools

        return await asyncio.to_thread(functools.partial(self.run, **arguments))

    def bind_schema(self, schema: ToolSchema) -> None:
        self.schema = schema


AbstractTool = Tool