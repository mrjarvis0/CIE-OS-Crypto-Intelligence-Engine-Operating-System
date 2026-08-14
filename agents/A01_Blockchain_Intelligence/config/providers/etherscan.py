"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    config.providers.etherscan

Purpose:
    Etherscan-family provider configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .blockchain import BlockchainProviderConfig, ProviderKind


@dataclass(frozen=True, slots=True)
class EtherscanConfig(BlockchainProviderConfig):
    api_url: str = "https://api.etherscan.io/api"
    api_key_secret: str = "ETHERSCAN_API_KEY"

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.api_url.strip():
            raise ValueError("api_url cannot be empty")
        if not self.api_key_secret.strip():
            raise ValueError("api_key_secret cannot be empty")

    def as_dict(self) -> dict[str, Any]:
        data = super().as_dict()
        data.update(
            {
                "kind": ProviderKind.BLOCKCHAIN.value,
                "api_url": self.api_url,
                "api_key_secret": self.api_key_secret,
            }
        )
        return data
