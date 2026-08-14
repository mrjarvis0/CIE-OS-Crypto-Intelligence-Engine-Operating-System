"""
Tools :: Schemas :: Tool
========================

Canonical data contract for a Tool definition.

Every tool registered in the platform is described by :class:`ToolSchema` (or
its lightweight in-memory counterpart :class:`ToolDefinition`). These types are
transport- and implementation-agnostic; they only describe *what* the tool
expects to consume and produce, plus the capabilities and permissions needed
to use it.

The schemas never execute logic. Higher layers (core, discovery, routing,
governance) depend on these structures rather than inventing their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..utils.ids import new_name_id

__all__ = ["ToolSchema", "ToolDefinition", "ParameterSchema", "parameter"]


@dataclass(frozen=True)
class ParameterSchema:
    """
    Describes a single input parameter accepted by a tool.

    ``type`` uses the JSON-Schema style names (``string``, ``integer``,
    ``number``, ``boolean``, ``array``, ``object``).  ``required=True`` marks
    the parameter mandatory for execution.
    """

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None
    enum: Sequence[Any] = field(default_factory=list)


InputTypes = Sequence[Mapping[str, Any]]
OutputTypes = Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class ToolSchema:
    """
    The canonical, immutable description of a tool.

    Fields
    ------
    name:
        Stable lowercase kebab id, unique within its namespace.
    namespace:
        Grouping scope (``security``, ``blockchain``, ``marketplace`` ...).
    display_name:
        Human-friendly label shown to operators.
    description:
        What the tool does and when it should be chosen.
    version:
        Semantic version string.
    capabilities:
        Capability ids this tool provides (``BLOCKCHAIN_READ`` ...).
    category:
        High-level grouping used by Discovery/Geography.
    author:
        Owning identity recorded in governance metadata.
    parameters:
        Ordered accepted input parameters.
    outputs:
        Ordered shape of the response payload.
    permission:
        Required permission key (granted by the security layer).
    tags:
        Free-form search terms for discovery; never user-facing.
    metadata:
        Adhoc key/values (latency class, cost rating, ...).
    """

    name: str
    description: str = ""
    namespace: str = "core"
    display_name: str = ""
    version: str = "1.0.0"
    capabilities: Sequence[str] = field(default_factory=list)
    category: str = "general"
    author: str = ""
    parameters: Sequence[Mapping[str, Any]] = field(default_factory=list)
    output: Sequence[Mapping[str, Any]] = field(default_factory=list)
    permission: str = ""
    tags: Sequence[str] = field(default_factory=list)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tool name is required")
        if not self.description:
            raise ValueError("tool description is required")

    @property
    def qualified_name(self) -> str:
        """``namespace.name`` composite used by registry lookups."""
        return f"{self.namespace}:{self.name}" if self.namespace else self.name

    def parameter_names(self) -> Sequence[str]:
        return [p.get("name", "") for p in self.parameters]

    def require_capabilities(self, required: Sequence[str]) -> bool:
        want = set(required)
        return want.issubset(self.capabilities)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "capabilities": list(self.capabilities),
            "category": self.category,
            "author": self.author,
            "parameters": [dict(p) for p in self.parameters],
            "output": [dict(o) for o in self.output],
            "permission": self.permission,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ToolSchema":
        return cls(
            name=str(data.get("name", "")),
            namespace=str(data.get("namespace", "core")),
            display_name=str(data.get("display_name", "")),
            description=str(data.get("description", "")),
            version=str(data.get("version", "1.0.0")),
            capabilities=list(data.get("capabilities", [])),
            category=str(data.get("category", "general")),
            author=str(data.get("author", "")),
            parameters=[dict(p) for p in data.get("parameters", [])],
            output=[dict(o) for o in data.get("output", [])],
            permission=str(data.get("permission", "")),
            tags=list(data.get("tags", [])),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def build(
        cls,
        *,
        name: str,
        func: Any = None,
        description: str = "",
        namespace: str = "core",
        **kwargs: Any,
    ) -> "ToolSchema":
        """
        Convenience constructor for wiring plain callables into the registry.

        When ``name`` is empty and ``func`` is provided a name is derived from
        the callable's ``__name__`` via :func:`new_name_id`. Remaining kwargs
        are forwarded to the primary constructor.
        """
        if not name and func is not None:
            name = new_name_id(getattr(func, "__name__", "tool"))
        return cls(name=name, namespace=namespace, description=description, **kwargs)


@dataclass(frozen=True)
class ToolDefinition:
    """
    Runtime representation linking a :class:`ToolSchema` to a callable/adapter
    reference. Used by the registry before execution; the executors read the
    concrete ``target`` off this object.
    """

    schema: ToolSchema
    target: Any = None
    adapter: str = ""
    enabled: bool = True
    version: str = "1.0.0"
    metadata: Mapping[str, Any] = field(default_factory=dict)


def parameter(
    name: str,
    type: str = "string",
    description: str = "",
    required: bool = True,
    default: Any = None,
) -> Dict[str, Any]:
    """Small factory producing a parameter dict compatible with ``ToolSchema``."""
    return {
        "name": name,
        "type": type,
        "description": description,
        "required": required,
        "default": default,
    }