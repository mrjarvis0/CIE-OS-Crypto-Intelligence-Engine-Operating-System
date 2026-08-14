"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.providers.blockchain

Purpose:
    Base provider configuration types for blockchain-facing public APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class ProviderKind(StrEnum):
    BLOCKCHAIN = "blockchain"
    MARKET = "market"
    DEFI = "defi"
    SECURITY = "security"


@dataclass(frozen=True, slots=True)
class BlockchainProviderConfig:
    name: str
    base_url: str
    enabled: bool = True
    kind: ProviderKind = ProviderKind.BLOCKCHAIN
    rate_limit_per_minute: int = 60
    timeout_seconds: int = 30
    headers: Mapping[str, str] | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name cannot be empty")
        if not self.base_url.strip():
            raise ValueError("base_url cannot be empty")
        if self.rate_limit_per_minute <= 0:
            raise ValueError("rate_limit_per_minute must be > 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "enabled": self.enabled,
            "kind": self.kind.value,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "timeout_seconds": self.timeout_seconds,
            "headers": dict(self.headers or {}),
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class BlockchainProviderRegistry:
    providers: tuple[BlockchainProviderConfig, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        normalized: list[BlockchainProviderConfig] = []
        for provider in self.providers:
            key = provider.name.strip().upper()
            if key in seen:
                raise ValueError(f"duplicate provider: {provider.name!r}")
            seen.add(key)
            normalized.append(provider)
        object.__setattr__(self, "providers", tuple(normalized))

    def get(self, name: str) -> BlockchainProviderConfig:
        key = name.strip().upper()
        for provider in self.providers:
            if provider.name.strip().upper() == key:
                return provider
        raise KeyError(f"provider not found: {name!r}")

    def enabled(self) -> tuple[BlockchainProviderConfig, ...]:
        return tuple(p for p in self.providers if p.enabled)

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {provider.name: provider.as_dict() for provider in self.providers}
