"""
Tools :: Plugins :: Manifest
============================

Reads and validates plugin manifests (plugin.json).

Manifest fields: name, id, version, description, publisher, license,
capabilities, permissions, dependencies, entry point and runtime
requirements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["PluginManifest", "MANIFEST_FIELDS"]

MANIFEST_FIELDS = ("id", "name", "version")


@dataclass
class PluginManifest:
    """Parsed plugin.json descriptor."""

    id: str
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    publisher: str = ""
    license: str = "MIT"
    capabilities: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    entry_point: str = ""
    runtime_requirements: List[str] = field(default_factory=list)
    schema_version: str = "1.0"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PluginManifest":
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            version=str(data.get("version", "1.0.0")),
            description=str(data.get("description", "")),
            publisher=str(data.get("publisher", "")),
            license=str(data.get("license", "MIT")),
            capabilities=list(data.get("capabilities", [])),
            permissions=list(data.get("permissions", [])),
            dependencies=list(data.get("dependencies", [])),
            entry_point=str(data.get("entry_point", "")),
            runtime_requirements=list(data.get("runtime_requirements", [])),
            schema_version=str(data.get("schema_version", "1.0")),
        )

    def missing_fields(self) -> List[str]:
        return [field for field in MANIFEST_FIELDS if not getattr(self, field)]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "publisher": self.publisher,
            "license": self.license,
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "dependencies": list(self.dependencies),
            "entry_point": self.entry_point,
            "runtime_requirements": list(self.runtime_requirements),
            "schema_version": self.schema_version,
        }