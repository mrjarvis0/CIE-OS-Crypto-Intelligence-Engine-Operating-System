"""
Tools :: Plugins :: Updater
===========================

Plugin upgrades: version checks, compatibility validation, incremental
updates and rollback integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..marketplace.updates import compare_versions
from .manifest import PluginManifest
from .plugin import PluginState
from .registry import PluginRecord, PluginRegistry

__all__ = ["PluginUpdateResult", "PluginUpdater"]


@dataclass
class PluginUpdateResult:
    """Outcome of a plugin update."""

    plugin_id: str
    updated: bool
    from_version: str = ""
    to_version: str = ""
    detail: str = ""
    rolled_back: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "updated": self.updated,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "detail": self.detail,
            "rolled_back": self.rolled_back,
        }


class PluginUpdater:
    """Validating plugin updater with rollback."""

    def __init__(self, registry: Optional[PluginRegistry] = None) -> None:
        self.registry = registry if registry is not None else PluginRegistry()

    def update(self, plugin_id: str, new_manifest: PluginManifest) -> PluginUpdateResult:
        record = self.registry.get(plugin_id)
        if record is None:
            return PluginUpdateResult(plugin_id=plugin_id, updated=False, detail="plugin not installed")

        if new_manifest.id != plugin_id:
            return PluginUpdateResult(plugin_id=plugin_id, updated=False, detail="manifest id mismatch")

        order = compare_versions(record.version, new_manifest.version)
        if order >= 0:
            return PluginUpdateResult(plugin_id=plugin_id, updated=False, from_version=record.version, to_version=new_manifest.version, detail="no newer version")

        if not self._compatible(record, new_manifest):
            return PluginUpdateResult(plugin_id=plugin_id, updated=False, from_version=record.version, to_version=new_manifest.version, detail="incompatible update")

        self.registry.register_manifest(new_manifest)
        return PluginUpdateResult(plugin_id=plugin_id, updated=True, from_version=record.version, to_version=new_manifest.version, detail="updated")

    def _compatible(self, record: PluginRecord, manifest: PluginManifest) -> bool:
        if record.capabilities and not set(record.capabilities).issubset(set(manifest.capabilities)):
            return False
        return True

    def rollback(self, plugin_id: str, manifest: PluginManifest) -> PluginUpdateResult:
        self.registry.register_manifest(manifest)
        return PluginUpdateResult(plugin_id=plugin_id, updated=False, from_version="", to_version=manifest.version, detail="rolled back", rolled_back=True)