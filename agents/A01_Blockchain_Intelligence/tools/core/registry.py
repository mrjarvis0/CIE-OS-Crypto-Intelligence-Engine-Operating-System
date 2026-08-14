"""
Tools :: Core :: Registry
=========================

The tool registry: the single authoritative index of every known tool.

A registry maps names to :class:`Tool` instances, holds capability indexes,
and owns each tool's lifecycle machine. Registration is the only way a tool
enters the runtime; lookup is thread-safe and strict.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set

from ..schemas.registry import RegistryEntry, RegistryStats
from .exceptions import ToolNotFoundError, ToolNotEnabledError, ValidationError
from .lifecycle import LifecycleMachine
from .capability import CapabilitySet

__all__ = ["ToolRegistry", "RegistryEntry", "RegistryStats"]


class ToolRegistry:
    """
    Thread-safe name -> tool index with capability lookup.

    ``register`` stores the instance, attaches a fresh lifecycle machine and
    indexes declared capabilities. ``get``/``require`` raise the domain
    errors; ``list``/``search`` are pure reads.
    """

    def __init__(self, *, allow_overwrite: bool = False) -> None:
        self._lock = threading.RLock()
        self._tools: Dict[str, Any] = {}
        self._lifecycles: Dict[str, LifecycleMachine] = {}
        self._capability_index: Dict[str, Set[str]] = {}
        self.allow_overwrite = allow_overwrite

    # -- writes ------------------------------------------------------------ #

    def register(self, tool: Any, *, enabled: bool = True) -> None:
        name = getattr(tool, "name", "") or ""
        if not name:
            raise ValidationError("cannot register a tool without a name")
        with self._lock:
            if name in self._tools and not self.allow_overwrite:
                raise ValidationError(f"tool {name!r} already registered")
            self._tools[name] = tool
            machine = LifecycleMachine(initial="registered")
            machine.transition("enabled") if enabled else None
            self._lifecycles[name] = machine
            caps = self._declared_capabilities(tool)
            self._capability_index[name] = set(caps)

    def unregister(self, name: str) -> bool:
        with self._lock:
            self._tools.pop(name, None)
            self._lifecycles.pop(name, None)
            self._capability_index.pop(name, None)
        return name not in self._tools

    def enable(self, name: str) -> None:
        with self._lock:
            self._require_lifecycle(name).transition("enabled")

    def disable(self, name: str) -> None:
        with self._lock:
            self._require_lifecycle(name).transition("disabled")

    # -- reads ------------------------------------------------------------- #

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._tools

    def __len__(self) -> int:
        with self._lock:
            return len(self._tools)

    def get(self, name: str, *, strict: bool = False) -> Optional[Any]:
        with self._lock:
            tool = self._tools.get(name)
            if tool is None and strict:
                raise ToolNotFoundError(name)
            return tool

    def require(self, name: str) -> Any:
        tool = self.get(name, strict=True)
        assert tool is not None
        state = self._lifecycles[name].current
        if state not in ("enabled", "idle", "executing"):
            raise ToolNotEnabledError(f"tool {name!r} is not enabled (state={state!r})")
        return tool

    def list(self) -> Sequence[Any]:
        with self._lock:
            return tuple(self._tools[name] for name in sorted(self._tools))

    def names(self) -> Sequence[str]:
        with self._lock:
            return tuple(sorted(self._tools))

    def search(self, *, capability: str = "", name: str = "") -> Sequence[str]:
        with self._lock:
            results: List[str] = []
            for tool_name in sorted(self._tools):
                if name and name not in tool_name:
                    continue
                if capability:
                    caps = self._capability_index.get(tool_name, set())
                    if not any(capability == c for c in caps):
                        continue
                results.append(tool_name)
            return results

    def state(self, name: str) -> str:
        with self._lock:
            return self._require_lifecycle(name).current

    def capabilities(self, name: str) -> Sequence[str]:
        with self._lock:
            return tuple(sorted(self._capability_index.get(name, ())))

    # -- internals --------------------------------------------------------- #

    def _declared_capabilities(self, tool: Any) -> Sequence[str]:
        caps = getattr(tool, "capabilities", None)
        if caps:
            return [str(c) for c in caps]
        schema = getattr(tool, "schema", None)
        if schema is not None:
            return [str(c) for c in getattr(schema, "capabilities", ())]
        return ()

    def _require_lifecycle(self, name: str) -> LifecycleMachine:
        machine = self._lifecycles.get(name)
        if machine is None:
            raise ToolNotFoundError(name)
        return machine

    def stats(self) -> RegistryStats:
        with self._lock:
            return RegistryStats(
                total=len(self._tools),
                enabled=sum(1 for m in self._lifecycles.values() if m.current == "enabled"),
                disabled=sum(1 for m in self._lifecycles.values() if m.current == "disabled"),
                retired=sum(1 for m in self._lifecycles.values() if m.current == "retired"),
            )