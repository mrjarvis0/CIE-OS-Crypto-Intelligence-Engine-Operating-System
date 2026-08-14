"""
Tools :: Plugins :: Installer
=============================

Installs plugins: validate manifest, verify signature, resolve
dependencies, register and activate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .manifest import PluginManifest
from .plugin import PluginState
from .registry import PluginRegistry
from .signer import PluginSigner
from .validator import PluginValidation, PluginValidator

__all__ = ["PluginInstallResult", "PluginInstaller"]


@dataclass
class PluginInstallResult:
    """Outcome of one plugin installation."""

    plugin_id: str
    installed: bool
    detail: str = ""
    version: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "installed": self.installed,
            "detail": self.detail,
            "version": self.version,
        }


class PluginInstaller:
    """Transactional plugin installer."""

    def __init__(
        self,
        *,
        registry: Optional[PluginRegistry] = None,
        validator: Optional[PluginValidator] = None,
        signer: Optional[PluginSigner] = None,
    ) -> None:
        self.registry = registry if registry is not None else PluginRegistry()
        self.validator = validator if validator is not None else PluginValidator()
        self.signer = signer if signer is not None else PluginSigner()

    def install(
        self,
        manifest: PluginManifest,
        *,
        signature: str = "",
        publisher: str = "",
        check_dependencies: bool = True,
    ) -> PluginInstallResult:
        validation = self.validator.validate(
            manifest.as_dict(),
            signature=signature,
            publisher=publisher or manifest.publisher,
        )
        if not validation.passed:
            return PluginInstallResult(plugin_id=manifest.id, installed=False, detail="; ".join(validation.failures))

        if check_dependencies:
            for dep in manifest.dependencies:
                if self.registry.get(dep) is None:
                    return PluginInstallResult(plugin_id=manifest.id, installed=False, detail=f"missing dependency {dep!r}")

        self.registry.register_manifest(manifest)
        self.registry.set_state(manifest.id, PluginState.ACTIVATED)
        return PluginInstallResult(plugin_id=manifest.id, installed=True, detail="installed", version=manifest.version)