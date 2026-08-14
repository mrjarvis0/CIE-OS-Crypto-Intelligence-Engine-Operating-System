"""
Tools :: Plugins Layer
======================

The extensibility framework of the CIE-OS Tools platform: safely load,
manage, isolate, execute, update and unload plugins.

A plugin may provide new tools, agent skills, adapters, hooks, MCP
servers or workflows without modifying the core.

Modules: plugin, manifest, validator, registry, loader, sandbox, signer,
installer, updater, uninstaller. :class:`PluginManager` is the central
controller.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional, Sequence

__all__ = [
    "PluginError",
    "Plugin",
    "PluginState",
    "PluginManifest",
    "MANIFEST_FIELDS",
    "PluginValidation",
    "PluginValidator",
    "PluginRecord",
    "PluginRegistry",
    "PluginLoader",
    "PluginFactory",
    "SandboxLimits",
    "SandboxResult",
    "Sandbox",
    "PluginSigner",
    "PluginInstallResult",
    "PluginInstaller",
    "PluginUpdateResult",
    "PluginUpdater",
    "PluginUninstallResult",
    "PluginUninstaller",
    "PluginManager",
]

logger = logging.getLogger(__name__)


class PluginError(Exception):
    """Base class for every error raised by the plugins layer."""


from .plugin import Plugin, PluginState  # noqa: E402
from .manifest import PluginManifest, MANIFEST_FIELDS  # noqa: E402
from .validator import PluginValidation, PluginValidator  # noqa: E402
from .registry import PluginRecord, PluginRegistry  # noqa: E402
from .loader import PluginLoader, PluginFactory  # noqa: E402
from .sandbox import SandboxLimits, SandboxResult, Sandbox  # noqa: E402
from .signer import PluginSigner  # noqa: E402
from .installer import PluginInstallResult, PluginInstaller  # noqa: E402
from .updater import PluginUpdateResult, PluginUpdater  # noqa: E402
from .uninstaller import PluginUninstallResult, PluginUninstaller  # noqa: E402


class PluginManager:
    """Central plugin controller: install, enable, disable, update, remove."""

    def __init__(
        self,
        *,
        registry: Optional[PluginRegistry] = None,
        installer: Optional[PluginInstaller] = None,
        updater: Optional[PluginUpdater] = None,
        uninstaller: Optional[PluginUninstaller] = None,
        loader: Optional[PluginLoader] = None,
        sandbox: Optional[Sandbox] = None,
    ) -> None:
        self.registry = registry if registry is not None else PluginRegistry()
        self.installer = installer if installer is not None else PluginInstaller(registry=self.registry)
        self.updater = updater if updater is not None else PluginUpdater(registry=self.registry)
        self.uninstaller = uninstaller if uninstaller is not None else PluginUninstaller(registry=self.registry)
        self.loader = loader if loader is not None else PluginLoader()
        self.sandbox = sandbox if sandbox is not None else Sandbox()

    def install(self, manifest: PluginManifest, **kwargs: Any) -> PluginInstallResult:
        return self.installer.install(manifest, **kwargs)

    def update(self, plugin_id: str, new_manifest: PluginManifest) -> PluginUpdateResult:
        return self.updater.update(plugin_id, new_manifest)

    def uninstall(self, plugin_id: str, **kwargs: Any) -> PluginUninstallResult:
        return self.uninstaller.uninstall(plugin_id, **kwargs)

    def load(self, manifest: PluginManifest):
        return self.loader.load(manifest)

    def execute(self, plugin_id: str, action: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        """Load and execute a plugin action inside the sandbox."""
        record = self.registry.require(plugin_id)
        manifest = PluginManifest(
            id=record.plugin_id,
            name=record.name,
            version=record.version,
            capabilities=record.capabilities,
            publisher=record.publisher,
        )
        plugin = self.loader.load(manifest)
        result = self.sandbox.run(plugin.execute, action, dict(params or {}))
        if not result.ok:
            raise PluginError(result.error)
        return result.value