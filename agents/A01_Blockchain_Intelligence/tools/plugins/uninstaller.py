"""
Tools :: Plugins :: Uninstaller
===============================

Safely removes plugins: stop execution, cleanup resources, remove
registry entries and preserve audit history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .plugin import PluginState
from .registry import PluginRecord, PluginRegistry

__all__ = ["PluginUninstallResult", "PluginUninstaller"]


@dataclass
class PluginUninstallResult:
    """Outcome of a plugin uninstall."""

    plugin_id: str
    removed: bool
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "removed": self.removed,
            "detail": self.detail,
        }


class PluginUninstaller:
    """Removes plugins and records the removal."""

    def __init__(self, registry: Optional[PluginRegistry] = None) -> None:
        self.registry = registry if registry is not None else PluginRegistry()
        self._history: List[Dict[str, Any]] = []

    def uninstall(self, plugin_id: str, *, force: bool = False) -> PluginUninstallResult:
        record = self.registry.get(plugin_id)
        if record is None:
            return PluginUninstallResult(plugin_id=plugin_id, removed=False, detail="plugin not installed")

        dependents = [r for r in self.registry.all() if plugin_id in r.dependencies]
        if dependents and not force:
            return PluginUninstallResult(plugin_id=plugin_id, removed=False, detail=f"blocked by dependents: {[d.plugin_id for d in dependents]}")

        removed = self.registry.unregister(plugin_id)
        self._history.append({"plugin_id": plugin_id, "version": record.version, "state": PluginState.UNINSTALLED})
        return PluginUninstallResult(plugin_id=plugin_id, removed=removed is not None, detail="uninstalled")

    def history(self, limit: int = 100) -> List[Dict[str, Any]]:
        return list(self._history[-max(1, int(limit)):])