"""
Tools :: Core :: Capability
===========================

Capability system: the coarse-grained vocabulary the Planner uses to route
execution intent to tools without naming concrete implementations.

Reuses the schema capability constants and adds capability-set helpers used
by the registry index and executor gating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence, Set

from ..schemas.capability import CAPABILITY
from .exceptions import ValidationError

__all__ = ["CapabilityId", "CapabilitySet", "resolve_capabilities", "requires", "CAPABILITY"]


@dataclass(frozen=True)
class CapabilityId:
    """Typed capability name with a short description."""

    name: str
    description: str = ""

    def __str__(self) -> str:
        return self.name

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, CapabilityId):
            return self.name == other.name
        if isinstance(other, str):
            return self.name == other
        return NotImplemented


class CapabilitySet:
    """
    Immutable set of capability ids with common query helpers.

    ``requires(...)`` returns a *matching* set when the tool declares at
    least the requested ids; ``missing(...)`` reports the gap.
    """

    def __init__(self, capabilities: Iterable[str]) -> None:
        self._items: Set[str] = set()
        for capability in capabilities:
            capability = str(capability)
            if capability:
                self._items.add(capability)

    def __contains__(self, capability: object) -> bool:
        return str(capability) in self._items

    def __iter__(self) -> Any:
        return iter(sorted(self._items))

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"CapabilitySet({sorted(self._items)!r})"

    @property
    def names(self) -> Sequence[str]:
        return tuple(sorted(self._items))

    def requires(self, *capabilities: str) -> bool:
        """True when all ``capabilities`` are present."""
        return all(str(c) in self._items for c in capabilities)

    def supports_any(self, capabilities: Iterable[str]) -> bool:
        """True when any of ``capabilities`` is present."""
        return any(str(c) in self._items for c in capabilities)

    def missing(self, *capabilities: str) -> Sequence[str]:
        """Ids from ``capabilities`` that are absent."""
        return tuple(c for c in capabilities if str(c) not in self._items)

    def union(self, other: Any) -> "CapabilitySet":
        other_items = other.names if isinstance(other, CapabilitySet) else other
        return CapabilitySet(set(self._items) | set(other_items or ()))

    def as_dict(self) -> Mapping[str, Any]:
        return {"capabilities": self.names}


def resolve_capabilities(names: Iterable[str]) -> CapabilitySet:
    """Normalize a sequence of capability names into a :class:`CapabilitySet`."""
    return CapabilitySet(names)


def requires(tool: Any, *requirements: str) -> None:
    """
    Validate a tool declares the requested capabilities.

    Raises :class:`ValidationError` listing the missing ids. Intended for the
    registry's registration gate.
    """
    set_attr = getattr(tool, "capabilities", None)
    if set_attr is None:
        schema = getattr(tool, "schema", None)
        if schema is not None:
            set_attr = getattr(schema, "capabilities", ())
        else:
            set_attr = ()
    if not set_attr:
        raise ValidationError(f"tool {getattr(tool, 'name', '?')!r} declares no capabilities")
    missing = [c for c in requirements if str(c) not in set_attr]
    if missing:
        raise ValidationError(
            f"tool {getattr(tool, 'name', '?')!r} missing required capabilities: {missing}"
        )