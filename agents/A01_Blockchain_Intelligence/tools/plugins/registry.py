"""
Tools :: Plugins :: Registry
============================

Installed plugin inventory: source of truth for plugin IDs, versions,
states, capabilities and dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .manifest import PluginManifest
from .plugin import Plugin, PluginState

__all__ = ["PluginRecord", "PluginRegistry"]


@dataclass
class PluginRecord:
    """One installed plugin entry."""

    plugin_id: str
    version: str
    state: str = PluginState.INSTALLED
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    publisher: str = ""
    name: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "state": self.state,
            "capabilities": list(self.capabilities),
            "dependencies": list(self.dependencies),
            "publisher": self.publisher,
        }


class PluginRegistry:
    """Registry of installed plugins."""

    def __init__(self) -> None:
        self._records: Dict[str, PluginRecord] = {}

    def register(self, record: PluginRecord) -> PluginRecord:
        self._records[record.plugin_id] = record
        return record

    def register_manifest(self, manifest: PluginManifest) -> PluginRecord:
        return self.register(
            PluginRecord(
                plugin_id=manifest.id,
                version=manifest.version,
                capabilities=list(manifest.capabilities),
                dependencies=list(manifest.dependencies),
                publisher=manifest.publisher,
                name=manifest.name,
            )
        )

    def get(self, plugin_id: str) -> Optional[PluginRecord]:
        return self._records.get(plugin_id)

    def require(self, plugin_id: str) -> PluginRecord:
        record = self.get(plugin_id)
        if record is None:
            raise KeyError(f"plugin {plugin_id!r} not installed")
        return record

    def set_state(self, plugin_id: str, state: str) -> PluginRecord:
        record = self.require(plugin_id)
        record.state = state
        return record

    def unregister(self, plugin_id: str) -> Optional[PluginRecord]:
        return self._records.pop(plugin_id, None)

    def by_state(self, state: str) -> List[PluginRecord]:
        return [record for record in self._records.values() if record.state == state]

    def by_capability(self, capability: str) -> List[PluginRecord]:
        return [record for record in self._records.values() if capability in record.capabilities]

    def all(self) -> List[PluginRecord]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)