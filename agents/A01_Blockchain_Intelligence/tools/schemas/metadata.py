"""
Tools :: Schemas :: Metadata
============================

Canonical metadata contract describing any platform artifact: tools, plugins,
agents, packages, adapters and skills.

Metadata is descriptive data only; it never contains executable logic. The
Registry, Discovery, Marketplace, Governance and Planning layers all consume
the same ``ToolMetadata`` shape so that search and ranking behave uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence


@dataclass(frozen=True)
class ToolMetadata:
    """
    Immutable description of a platform artifact.

    Fields align with the Registry schema and the Marketplace manifest so a
    package can be published, indexed and installed without reshaping data.

    ``name`` is the stable unique id; ``namespace`` groups artifacts; type is
    one of ``tool``, ``plugin``, ``adapter``, ``agent``, ``skill``, ``package``.
    """

    name: str = ""
    namespace: str = "core"
    type: str = "tool"
    description: str = ""
    version: str = "1.0.0"
    category: str = "general"
    tags: Sequence[str] = field(default_factory=list)
    capabilities: Sequence[str] = field(default_factory=list)
    permissions: Sequence[str] = field(default_factory=list)
    author: str = ""
    license: str = ""
    homepage: str = ""
    repository: str = ""
    status: str = "available"          # available | installed | deprecated | retired
    trust_score: float = 0.0           # 0..1
    downloads: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}:{self.name}" if self.namespace else self.name

    def with_extra(self, **values: Any) -> "ToolMetadata":
        merged = dict(self.metadata)
        merged.update(values)
        data = self.as_dict()
        data["metadata"] = merged
        return ToolMetadata.from_dict(data)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "namespace": self.namespace,
            "type": self.type,
            "description": self.description,
            "version": self.version,
            "category": self.category,
            "tags": list(self.tags),
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "author": self.author,
            "license": self.license,
            "homepage": self.homepage,
            "repository": self.repository,
            "status": self.status,
            "trust_score": self.trust_score,
            "downloads": self.downloads,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ToolMetadata":
        return cls(
            name=str(data.get("name", "")),
            namespace=str(data.get("namespace", "core")),
            type=str(data.get("type", "tool")),
            description=str(data.get("description", "")),
            version=str(data.get("version", "1.0.0")),
            category=str(data.get("category", "general")),
            tags=list(data.get("tags", [])),
            capabilities=list(data.get("capabilities", [])),
            permissions=list(data.get("permissions", [])),
            author=str(data.get("author", "")),
            license=str(data.get("license", "")),
            homepage=str(data.get("homepage", "")),
            repository=str(data.get("repository", "")),
            status=str(data.get("status", "available")),
            trust_score=float(data.get("trust_score", 0.0)),
            downloads=int(data.get("downloads", 0)),
            metadata=dict(data.get("metadata", {})),
        )

# Backward-compatible loose alias (the README refers to the schema as "
def metadata_dict(name: str, **overrides: Any) -> Dict[str, Any]:
    """Build a metadata dict with sensible defaults."""
    base = ToolMetadata(name=name).as_dict()
    base.update(overrides)
    return base
