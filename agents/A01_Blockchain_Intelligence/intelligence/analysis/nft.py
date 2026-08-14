"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.nft

Purpose:
    NFT analysis.

    Profiles an NFT collection by floor price, supply, and trading
    momentum.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer


class NftAnalyzer(BaseAnalyzer):
    """
    Produces an NFT collection summary.
    """

    name = "nft"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        collection = self._get(subject, "name")
        floor_price = self._get(subject, "floor_price", 0)
        supply = self._get(subject, "supply", 0)
        volume_24h = self._get(subject, "volume_24h", 0)

        data = {
            "name": collection,
            "floor_price": floor_price,
            "supply": supply,
            "volume_24h": volume_24h,
            "royalty": self._get(subject, "royalty"),
            "mint_price": self._get(subject, "mint_price"),
        }
        artifact = self._evidence(
            claim=f"NFT collection {collection} has floor {floor_price} with supply {supply}",
            data=data,
            source_type="market",
            confidence=0.5,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"NFT collection {collection}: floor {floor_price}",
            confidence=0.5,
        )
