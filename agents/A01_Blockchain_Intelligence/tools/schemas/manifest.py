"""
Tools :: Schemas :: Manifest
============================

Deployment manifest contract describing how an artifact (tool, plugin, adapter,
agent) is bundled, wired and verified.

Manifests are what the Lifecycle and Plugin layers consume when installing or
upgrading. They are deliberately declarative -- checksums and signatures are
strings produced by the utilities layer; the manifest itself never executes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence


@dataclass
class Dependency:
    """A single artifact dependency with version constraint."""

    name: str = ""
    version: str = "*"
    optional: bool = False
    scope: str = "runtime"  # runtime | development | build

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "optional": self.optional,
            "scope": self.scope,
        }


@dataclass
class Checksum:
    """Integrity descriptor for an artifact payload."""

    algorithm: str = "sha256"
    value: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"algorithm": self.algorithm, "value": self.value}


@dataclass
class Manifest:
    """
    Declarative description of a deployable artifact.

    Fields:
    - identity: name, namespace, version, type
    - entry_point: how the artifact is exposed at runtime (module path or
      adapter name)
    - dependencies: required sibling artifacts
    - capabilities: permissions requested at runtime
    - runtime: python version, resource hints
    - checksum / signature: integrity protection from the security layer
    """

    name: str = ""
    namespace: str = "core"
    version: str = "1.0.0"
    type: str = "tool"  # tool | plugin | agent | skill | package
    description: str = ""
    entry_point: str = ""
    author: str = ""
    license: str = ""
    homepage: str = ""
    dependencies: Sequence[Dependency] = field(default_factory=list)
    dependencies_raw: Optional[Sequence[Mapping[str, Any]]] = None
    capabilities: Sequence[str] = field(default_factory=list)
    permissions: Sequence[str] = field(default_factory=list)
    runtime: Mapping[str, Any] = field(default_factory=lambda: {"python": ">=3.10"})
    checksum: Optional[Checksum] = None
    signature: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}:{self.name}" if self.namespace else self.name

    def dependency_names(self) -> Sequence[str]:
        return [d.name for d in self.dependencies]

    def requires(self, capability: str) -> bool:
        return capability in self.capabilities

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "version": self.version,
            "type": self.type,
            "description": self.description,
            "entry_point": self.entry_point,
            "author": self.author,
            "license": self.license,
            "homepage": self.homepage,
            "dependencies": [d.as_dict() for d in self.dependencies],
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "runtime": dict(self.runtime),
            "checksum": self.checksum.as_dict() if self.checksum else None,
            "signature": self.signature,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Manifest":
        deps = [
            Dependency(
                name=str(d.get("name", "")),
                version=str(d.get("version", "*")),
                optional=bool(d.get("optional", False)),
                scope=str(d.get("scope", "custom")),
            )
            for d in data.get("dependencies", [])
        ]
        checksum_data = data.get("checksum")
        checksum = (
            Checksum(algorithm=str(checksum_data.get("algorithm", "sha256")), value=str(checksum_data.get("value", "")))
            if isinstance(checksum_data, Mapping)
            else None
        )
        return cls(
            name=str(data.get("name", "")),
            namespace=str(data.get("namespace", "core")),
            version=str(data.get("version", "1.0.0")),
            type=str(data.get("type", "tool")),
            description=str(data.get("description", "")),
            entry_point=str(data.get("entry_point", "")),
            author=str(data.get("author", "")),
            license=str(data.get("license", "")),
            homepage=str(data.get("homepage", "")),
            dependencies=deps,
            capabilities=list(data.get("capabilities", [])),
            permissions=list(data.get("permissions", [])),
            runtime=dict(data.get("runtime", {})),
            checksum=checksum,
            signature=str(data.get("signature", "")),
            extra=dict(data.get("extra", {})),
        )