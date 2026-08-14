"""
Tools :: Plugins :: Plugin
==========================

The base plugin interface: identity, metadata, lifecycle hooks and
capability declaration. Every plugin implements this interface.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["Plugin", "PluginState"]

_PLUGIN_STATES = ("discovered", "validated", "installed", "registered", "configured", "loaded", "activated", "running", "paused", "disabled", "uninstalled")


class PluginState:
    DISCOVERED = "discovered"
    VALIDATED = "validated"
    INSTALLED = "installed"
    REGISTERED = "registered"
    CONFIGURED = "configured"
    LOADED = "loaded"
    ACTIVATED = "activated"
    RUNNING = "running"
    PAUSED = "paused"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"


@dataclass
class Plugin:
    """Base plugin implementation; subclass for real plugins."""

    plugin_id: str
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    publisher: str = ""
    capabilities: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    state: str = PluginState.DISCOVERED
    entry_point: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.plugin_id

    # -- lifecycle hooks (overridable) ----------------------------------------- #

    def initialize(self, context: Optional[Mapping[str, Any]] = None) -> None:
        self.state = PluginState.CONFIGURED

    def activate(self, context: Optional[Mapping[str, Any]] = None) -> None:
        self.state = PluginState.ACTIVATED

    def deactivate(self, reason: str = "") -> None:
        self.state = PluginState.DISABLED

    def shutdown(self) -> None:
        self.state = PluginState.UNINSTALLED

    # -- execution --------------------------------------------------------------- #

    def execute(self, action: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        """Default implementation: only the ``ping`` action is supported."""
        if action == "ping":
            return {"plugin_id": self.plugin_id, "version": self.version}
        raise NotImplementedError(f"plugin {self.plugin_id!r} does not implement {action!r}")

    # -- metadata ----------------------------------------------------------------- #

    def as_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "publisher": self.publisher,
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "state": self.state,
            "entry_point": self.entry_point,
        }