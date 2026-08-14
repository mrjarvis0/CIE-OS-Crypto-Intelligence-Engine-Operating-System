"""
Tools :: Schemas :: Capability
==============================

Capability contract: the smallest, provider-neutral unit of what a tool can do.

The Planning Engine routes requests using capabilities instead of concrete
implementations. This module defines the canonical capability constants plus
a wrapper type so the core, discovery and routing layers share a single
vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

__all__ = [
    "Capability",
    "CAPABILITY",
    "all_capabilities",
    "capabilities_from",
]


class CAPABILITY:
    """Registry of well-known capabilities (const namespace)."""

    READ_DATA = "DATA_READ"
    WRITE_DATA = "DATA_WRITE"
    NETWORK_ACCESS = "NETWORK_ACCESS"
    FILE_READ = "FILE_READ"
    FILE_WRITE = "FILE_WRITE"
    BLOCKCHAIN_READ = "BLOCKCHAIN_READ"
    BLOCKCHAIN_WRITE = "BLOCKCHAIN_WRITE"
    LLM_CALL = "LLM_CALL"
    EMBEDDING = "EMBEDDING"
    IMAGE_PROCESSING = "IMAGE_PROCESSING"
    SPEECH = "SPEECH"
    WEB_SEARCH = "WEB_SEARCH"
    WEB_CRAWL = "WEB_CRAWL"
    HTTP_CLIENT = "HTTP_CLIENT"
    MCP_CLIENT = "MCP_CLIENT"
    DATABASE_QUERY = "DATABASE_QUERY"
    CONTRACT_CALL = "CONTRACT_CALL"
    SCRIPT_EXECUTION = "SCRIPT_EXECUTION"
    PROCESS_EXECUTION = "PROCESS_EXECUTION"
    SECRET_MANAGEMENT = "SECRET_MANAGEMENT"
    MARKETPLACE = "MARKETPLACE"


def all_capabilities() -> Sequence[str]:
    """All well-known capability constant values."""
    return [
        value
        for key, value in vars(CAPABILITY).items()
        if key.isupper() and isinstance(value, str)
    ]


@dataclass(frozen=True)
class Capability:
    """Immutable description of a single capability."""

    name: str
    description: str = ""
    required_permission: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required_permission": self.required_permission,
            "metadata": dict(self.metadata),
        }


def capabilities_from(names: Sequence[str]) -> Sequence[Capability]:
    """Build :class:`Capability` descriptors from plain string names."""
    return [Capability(name=n) for n in names if isinstance(n, str) and n]