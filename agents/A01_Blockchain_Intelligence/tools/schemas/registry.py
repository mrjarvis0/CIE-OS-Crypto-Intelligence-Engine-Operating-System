"""
Tools :: Schemas :: Registry
============================

Registry contract: the durable record of a registered tool.

The registry (core/registry.py) stores these records so the discovery, routing
and governance layers can inspect tool state without re-resolving the
implementation. States follow the lifecycle vocabulary defined in the core
layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from ..utils.ids import new_id

__all__ = ["RegistryEntry", "RegistryStats"]


@dataclass
class RegistryEntry:
    """
    State record for a single registered tool.

    ``schema``/``definition`` are kept by reference; the record itself adds
    runtime state (enabled, health, usage counters and the registration id).
    """

    entry_id: str = field(default_factory=lambda: new_id(prefix="te"))
    tool: str = ""
    version: str = "1.0.0"
    namespace: str = "core"
    state: str = "registered"   # discovered|loaded|registered|enabled|disabled|retired
    enabled: bool = True
    health: str = "unknown"     # unknown|ok|degraded|down
    schema: Optional[Any] = None
    definition: Optional[Any] = None
    created_at: str = ""
    updated_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}:{self.tool}" if self.namespace else self.tool

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "entry_id": self.entry_id,
            "tool": self.tool,
            "version": self.version,
            "namespace": self.namespace,
            "state": self.state,
            "enabled": self.enabled,
            "health": self.health,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def create(
        cls,
        tool: str,
        *,
        version: str = "1.0.0",
        namespace: str = "core",
        schema: Any = None,
        definition: Any = None,
        **metadata: Any,
    ) -> "RegistryEntry":
        return cls(
            tool=tool,
            version=version,
            namespace=namespace,
            schema=schema,
            definition=definition,
            metadata=metadata,
        )


@dataclass
class RegistryStats:
    """Aggregate counts over a registry snapshot."""

    total: int = 0
    enabled: int = 0
    disabled: int = 0
    healthy: int = 0
    degraded: int = 0
    down: int = 0
    retired: int = 0
    namespaces: int = 0

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "total": self.total,
            "enabled": self.enabled,
            "disabled": self.disabled,
            "healthy": self.healthy,
            "degraded": self.degraded,
            "down": self.down,
            "retired": self.retired,
            "namespaces": self.namespaces,
        }