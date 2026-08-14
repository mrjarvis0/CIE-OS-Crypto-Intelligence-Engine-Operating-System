"""
Tools :: Core :: Dependency
===========================

Dependency graph for tool loading.

Models the load-time dependency relationships between tools and their
payloads. The loader consults this graph to guarantee a deterministic,
stable topo-sorted load order and to reject cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from .exceptions import DependencyError

__all__ = ["DependencyGraph", "DependencyNode", "DependencySpec"]


@dataclass
class DependencySpec:
    """Static declared dependency of one node on another."""

    name: str
    version: str = ""
    optional: bool = False

    def to_dict(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "optional": self.optional,
        }


@dataclass
class DependencyNode:
    """One vertex in the graph: an installable/loadable unit."""

    name: str
    data: Any = None
    dependencies: List[DependencySpec] = field(default_factory=list)


class DependencyGraph:
    """
    Directed acyclic graph over named nodes.

    ``add`` registers a node with its dependency specs; ``resolve`` returns a
    topo-ordered list of node names such that dependencies come before
    dependents. Cycles raise :class:`DependencyError`.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, DependencyNode] = {}

    def __contains__(self, name: str) -> bool:
        return name in self._nodes

    def add(self, name: str, data: Any = None, **deps: Any) -> "DependencyNode":
        """Register a node. ``**deps`` maps dep-name -> spec dict or str."""
        node = self._nodes.get(name)
        if node is None:
            node = DependencyNode(name=name, data=data)
            self._nodes[name] = node
        for dep_name, spec in deps.items():
            if isinstance(spec, str):
                spec = DependencySpec(name=dep_name, version=spec or "")
            elif not isinstance(spec, DependencySpec):
                spec = DependencySpec(name=dep_name, version=str(spec or ""))
            node.dependencies.append(spec)
        return node

    def nodes(self) -> Sequence[str]:
        return tuple(sorted(self._nodes))

    def dependencies_of(self, name: str) -> Sequence[str]:
        node = self._nodes.get(name)
        if node is None:
            return ()
        return tuple(spec.name for spec in node.dependencies)

    def resolve(self) -> Sequence[str]:
        """Topological order with cycle detection (Kahn's algorithm)."""

        deps: Dict[str, Set[str]] = {}
        for name, node in self._nodes.items():
            deps[name] = set()
            for spec in node.dependencies:
                if spec.name in self._nodes:
                    deps[name].add(spec.name)

        order: List[str] = []
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def _visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise DependencyError(f"dependency cycle detected at {name!r}")
            visiting.add(name)
            for dep in sorted(deps.get(name, ())):
                _visit(dep)
            visiting.discard(name)
            visited.add(name)
            order.append(name)

        for name in sorted(deps):
            _visit(name)
        return order

    def as_dict(self) -> Mapping[str, object]:
        return {
            name: [spec.to_dict() for spec in node.dependencies]
            for name, node in self._nodes.items()
        }