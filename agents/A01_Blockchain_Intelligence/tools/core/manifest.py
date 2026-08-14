"""
Tools :: Core :: Manifest
=========================

Workload manifest: how a set of tools deploys together.

A manifest enumerates which tools (by name plus optional version range) are
required to satisfy a workload, along with declared capabilities and
lifecycle hints. The loader consumes manifests to produce a runnable set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .version import _satisfies
from .exceptions import VersionError

__all__ = ["Manifest", "ManifestItem", "build_manifest"]


@dataclass
class ManifestItem:
    """One named requirement in a manifest."""

    name: str
    version: str = "*"
    enable: bool = True

    def satisfied_by(self, version: str) -> bool:
        return _satisfies(version, self.version)

    def to_dict(self) -> Mapping[str, object]:
        return {"name": self.name, "version": self.version, "enable": self.enable}


@dataclass
class Manifest:
    """A plan of tools to load, with shared build metadata."""

    name: str
    items: List[ManifestItem] = field(default_factory=list)
    build: Mapping[str, Any] = field(default_factory=dict)
    requires: Sequence[str] = field(default_factory=tuple)

    def add_item(self, name: str, version: str = "*", *, enable: bool = True) -> ManifestItem:
        item = ManifestItem(name=name, version=version, enable=enable)
        self.items.append(item)
        return item

    def names(self) -> Sequence[str]:
        return tuple(item.name for item in self.items)

    def required(self) -> Sequence[str]:
        return tuple(item.name for item in self.items if item.enable)

    def missing(self, available: Mapping[str, str]) -> Sequence[str]:
        """Names required but not present (or not satisfying) in ``available``.

        ``available`` maps tool-name -> installed version string.
        """
        missing: List[str] = []
        for item in self.items:
            if not item.enable:
                continue
            version = available.get(item.name)
            if version is None or not item.satisfied_by(version):
                missing.append(item.name)
        return missing

    def as_dict(self) -> Mapping[str, object]:
        return {
            "name": self.name,
            "items": [item.to_dict() for item in self.items],
            "build": dict(self.build),
            "requires": list(self.requires),
        }


def build_manifest(
    name: str,
    items: Iterable[Mapping[str, Any]] = (),
    **build: Any,
) -> Manifest:
    """Convenience builder from a list of requirement dicts."""
    manifest = Manifest(name=name, build=build)
    for entry in items:
        manifest.add_item(
            str(entry.get("name", "")),
            str(entry.get("version", "*")),
            enable=bool(entry.get("enable", True)),
        )
    return manifest