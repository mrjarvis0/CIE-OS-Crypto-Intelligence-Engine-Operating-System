"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.providers.coingecko

Purpose:
    CoinGecko provider configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .blockchain import BlockchainProviderConfig, ProviderKind


@dataclass(frozen=True, slots=True)
class CoinGeckoConfig(BlockchainProviderConfig):
    api_url: str = "https://api.coingecko.com/api/v3"

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.api_url.strip():
            raise ValueError("api_url cannot be empty")

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data.update(
            {
                "kind": ProviderKind.MARKET.value,
                "api_url": self.api_url,
            }
        )
        return data
