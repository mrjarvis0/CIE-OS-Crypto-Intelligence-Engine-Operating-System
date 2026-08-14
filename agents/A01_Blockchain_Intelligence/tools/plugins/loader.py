"""
Tools :: Plugins :: Loader
==========================

Loads plugins into the runtime from manifests, packages or in-memory
factories. Supports lazy loading.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .manifest import PluginManifest
from .plugin import Plugin, PluginState

__all__ = ["PluginLoader", "PluginFactory"]

PluginFactory = Callable[[PluginManifest], Plugin]


class PluginLoader:
    """Registry of factories that materialize plugin instances."""

    def __init__(self) -> None:
        self._factories: Dict[str, PluginFactory] = {}
        self._loaded: Dict[str, Plugin] = {}

    def register_factory(self, plugin_id: str, factory: PluginFactory) -> None:
        self._factories[plugin_id] = factory

    def can_load(self, plugin_id: str) -> bool:
        return plugin_id in self._factories

    def load(self, manifest: PluginManifest) -> Plugin:
        """Materialize (and cache) a plugin instance from its manifest."""
        if manifest.id in self._loaded:
            return self._loaded[manifest.id]
        factory = self._factories.get(manifest.id)
        if factory is None:
            plugin = Plugin(
                plugin_id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                publisher=manifest.publisher,
                capabilities=list(manifest.capabilities),
                permissions=list(manifest.permissions),
                entry_point=manifest.entry_point,
            )
        else:
            plugin = factory(manifest)
        plugin.state = PluginState.LOADED
        self._loaded[manifest.id] = plugin
        return plugin

    def unload(self, plugin_id: str) -> Optional[Plugin]:
        return self._loaded.pop(plugin_id, None)

    def loaded(self) -> List[Plugin]:
        return list(self._loaded.values())