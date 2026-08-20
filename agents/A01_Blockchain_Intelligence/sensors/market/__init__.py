"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    sensors.market

Purpose:
    Sensors for off-chain market data -- prices, volumes, supply.

Market data is not decoration. DET-WHALE-01 applies a USD floor to transfers,
so without a price the detector cannot distinguish a $10 move from a $10M one.
The endpoints are already cataloged in ``blockchain.rpc.providers.catalog``
under ``ProviderRole.MARKET``; this package is the first consumer.
"""

from __future__ import annotations

from .price_sensor import (
    DEFAULT_CACHE_TTL,
    DEFILLAMA_COINS_BASE,
    HttpMarketClient,
    MarketResponse,
    PriceFeedSensor,
)

__all__ = [
    "DEFAULT_CACHE_TTL",
    "DEFILLAMA_COINS_BASE",
    "HttpMarketClient",
    "MarketResponse",
    "PriceFeedSensor",
]
