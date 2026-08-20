"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    sensors.market.price_sensor

Purpose:
    Read USD spot prices from market-data APIs so the pipeline can attach
    dollar values to on-chain observations.

Design goals:
    - Provider-agnostic: pluggable transport, tested without network I/O
    - Same envelope discipline as chain sensors (SensorResult, RawRecord,
      Provenance) so downstream code consumes prices through one interface
    - Prices captured raw; the sensor does not interpret materiality or rank
    - In-memory cache with configurable TTL respects provider rate limits
    - Unmapped chains return undetermined, never a guess

Notes:
    This sensor is deliberately separate from the chain-sensor hierarchy.
    A chain sensor reads on-chain state from a node; a price sensor reads
    off-chain market data from a vendor API.  Conflating the two would
    force every chain sensor to carry a price method it cannot fulfil from
    the chain itself, or force market queries through a transport built for
    JSON-RPC.

    The primary provider is DefiLlama's coins API (coins.llama.fi), which
    requires no API key and accepts both CoinGecko identifiers (for native
    assets) and ``chain:address`` pairs (for tokens).  The provider catalog
    in ``blockchain.rpc.providers.catalog`` already lists this endpoint;
    this sensor is the first consumer.

    Provenance follows the same rules as chain sensors: provider name is
    recorded, endpoint URL is not, timestamp is captured at observation.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

from ..envelope import Provenance, RawRecord, RecordKind, SensorResult

logger = logging.getLogger(__name__)

# -- Provider URL --------------------------------------------------------

DEFILLAMA_COINS_BASE: Final[str] = "https://coins.llama.fi"

# -- Chain-to-platform mappings ------------------------------------------

_CHAIN_TO_LLAMA: Final[dict[str, str]] = {
    "ethereum": "ethereum",
    "bnb_chain": "bsc",
    "polygon": "polygon",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "base": "base",
    "avalanche": "avax",
    "linea": "linea",
    "scroll": "scroll",
    "gnosis": "gnosis",
    "celo": "celo",
    "mantle": "mantle",
    "unichain": "unichain",
    "solana": "solana",
}

_CHAIN_TO_NATIVE_CGID: Final[dict[str, str]] = {
    "ethereum": "ethereum",
    "arbitrum": "ethereum",
    "optimism": "ethereum",
    "base": "ethereum",
    "linea": "ethereum",
    "scroll": "ethereum",
    "unichain": "ethereum",
    "bnb_chain": "binancecoin",
    "polygon": "matic-network",
    "avalanche": "avalanche-2",
    "gnosis": "xdai",
    "celo": "celo",
    "mantle": "mantle",
    "solana": "solana",
    "bitcoin": "bitcoin",
}

DEFAULT_CACHE_TTL: Final[int] = 30

_METHOD_NATIVE: Final[str] = "native_price"
_METHOD_TOKEN: Final[str] = "token_price"
_PROVIDER: Final[str] = "defillama-coins"


# -- Transport -----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MarketResponse:
    """The result of one HTTP GET to a market-data provider."""

    ok: bool
    body: Any
    provider: str
    duration_ms: float
    reason: str = ""


@runtime_checkable
class MarketClient(Protocol):
    """Injectable HTTP transport for market data."""

    def get(self, url: str, *, provider: str) -> MarketResponse: ...


class HttpMarketClient:
    """Default transport using stdlib urllib.  No external dependencies."""

    def get(self, url: str, *, provider: str) -> MarketResponse:
        start = time.monotonic()
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "CIE-OS/A01",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                elapsed = (time.monotonic() - start) * 1000
                return MarketResponse(
                    ok=True, body=body, provider=provider, duration_ms=elapsed
                )
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            elapsed = (time.monotonic() - start) * 1000
            return MarketResponse(
                ok=False,
                body=None,
                provider=provider,
                duration_ms=elapsed,
                reason=str(exc),
            )


# -- Sensor --------------------------------------------------------------

class PriceFeedSensor:
    """
    Reads USD spot prices from market-data APIs.

    Not a subclass of :class:`sensors.base.Sensor` -- that hierarchy is
    for on-chain data served by blockchain nodes.  This sensor reads
    off-chain market data but emits the same envelope types, so downstream
    code consumes prices and blocks through one result interface.
    """

    name: str = "price_feed"

    def __init__(
        self,
        *,
        client: MarketClient | None = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
        base_url: str = DEFILLAMA_COINS_BASE,
    ) -> None:
        if cache_ttl < 0:
            raise ValueError("cache_ttl must be >= 0")
        self._client: MarketClient = client if client is not None else HttpMarketClient()
        self._cache: dict[str, tuple[float, SensorResult]] = {}
        self._cache_ttl = cache_ttl
        self._base_url = base_url.rstrip("/")

    # -- reads -----------------------------------------------------------

    def native_price(self, chain: str) -> SensorResult:
        """
        USD spot price for a chain's native asset.

        Returns undetermined for chains with no known CoinGecko identifier.
        A zero price is a valid answer, not a failure.
        """
        if not chain or not isinstance(chain, str):
            raise ValueError("chain must be a non-empty string")

        chain = chain.strip().lower()
        cgid = _CHAIN_TO_NATIVE_CGID.get(chain)
        if cgid is None:
            return self._undetermined(
                _METHOD_NATIVE,
                chain=chain,
                reason=f"no native-asset identifier mapped for chain {chain!r}",
            )

        coin_key = f"coingecko:{cgid}"
        cache_key = f"native:{chain}"
        return self._fetch_price(
            coin_key, cache_key, chain=chain, method=_METHOD_NATIVE
        )

    def token_price(self, chain: str, contract: str) -> SensorResult:
        """
        USD spot price for a token identified by contract address.

        Returns undetermined when the chain has no DefiLlama platform
        mapping, or when the provider has no price for the contract.
        """
        if not chain or not isinstance(chain, str):
            raise ValueError("chain must be a non-empty string")
        if not contract or not isinstance(contract, str):
            raise ValueError("contract must be a non-empty string")

        chain = chain.strip().lower()
        contract = contract.strip().lower()
        llama_chain = _CHAIN_TO_LLAMA.get(chain)
        if llama_chain is None:
            return self._undetermined(
                _METHOD_TOKEN,
                chain=chain,
                reason=f"no DefiLlama platform mapped for chain {chain!r}",
            )

        coin_key = f"{llama_chain}:{contract}"
        cache_key = f"token:{chain}:{contract}"
        return self._fetch_price(
            coin_key,
            cache_key,
            chain=chain,
            method=_METHOD_TOKEN,
            contract=contract,
        )

    # -- cache -----------------------------------------------------------

    def _cached(self, key: str) -> SensorResult | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, result = entry
        if time.monotonic() - ts > self._cache_ttl:
            del self._cache[key]
            return None
        return result

    # -- fetch -----------------------------------------------------------

    def _fetch_price(
        self,
        coin_key: str,
        cache_key: str,
        *,
        chain: str,
        method: str,
        contract: str | None = None,
    ) -> SensorResult:
        cached = self._cached(cache_key)
        if cached is not None:
            return cached

        url = f"{self._base_url}/prices/current/{coin_key}"
        resp = self._client.get(url, provider=_PROVIDER)

        if not resp.ok:
            return self._undetermined(
                method,
                chain=chain,
                reason=resp.reason or "market API request failed",
                provider=resp.provider,
                duration_ms=resp.duration_ms,
            )

        body = resp.body
        if not isinstance(body, dict):
            return self._malformed(
                method,
                chain=chain,
                reason=f"expected dict, got {type(body).__name__}",
                provider=resp.provider,
                duration_ms=resp.duration_ms,
            )

        coins = body.get("coins")
        if not isinstance(coins, dict):
            return self._malformed(
                method,
                chain=chain,
                reason="response missing 'coins' dict",
                provider=resp.provider,
                duration_ms=resp.duration_ms,
            )

        entry = coins.get(coin_key)
        if not isinstance(entry, dict):
            return self._undetermined(
                method,
                chain=chain,
                reason=f"no price entry for {coin_key!r}",
                provider=resp.provider,
                duration_ms=resp.duration_ms,
            )

        price = entry.get("price")
        if not isinstance(price, (int, float)):
            return self._malformed(
                method,
                chain=chain,
                reason=f"price field is {type(price).__name__}, not a number",
                provider=resp.provider,
                duration_ms=resp.duration_ms,
            )

        payload: dict[str, Any] = {
            "chain": chain,
            "price_usd": float(price),
            "symbol": entry.get("symbol", ""),
            "confidence": entry.get("confidence"),
            "source_timestamp": entry.get("timestamp"),
        }
        if contract is not None:
            payload["contract"] = contract

        result = self._determined(
            method=method,
            chain=chain,
            payload=payload,
            provider=resp.provider,
            duration_ms=resp.duration_ms,
        )

        self._cache[cache_key] = (time.monotonic(), result)
        return result

    # -- health ----------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return {
            "sensor": self.name,
            "base_url": self._base_url,
            "cache_ttl": self._cache_ttl,
            "cached_entries": len(self._cache),
            "mapped_chains_native": sorted(_CHAIN_TO_NATIVE_CGID),
            "mapped_chains_token": sorted(_CHAIN_TO_LLAMA),
        }

    # -- result construction ---------------------------------------------

    def _determined(
        self,
        *,
        method: str,
        chain: str,
        payload: Any,
        provider: str,
        duration_ms: float,
    ) -> SensorResult:
        record = RawRecord(
            chain=chain,
            kind=RecordKind.PRICE,
            payload=payload,
            height=None,
            provenance=Provenance(
                provider=provider,
                chain=chain,
                method=method,
                outcome="ok",
            ),
        )
        return SensorResult(
            determined=True,
            record=record,
            chain=chain,
            method=method,
            outcome="ok",
            duration_ms=duration_ms,
        )

    def _undetermined(
        self,
        method: str,
        *,
        chain: str = "",
        reason: str = "",
        provider: str = "",
        duration_ms: float = 0.0,
    ) -> SensorResult:
        return SensorResult(
            determined=False,
            chain=chain,
            method=method,
            outcome="undetermined",
            reason=reason,
            duration_ms=duration_ms,
        )

    def _malformed(
        self,
        method: str,
        *,
        chain: str = "",
        reason: str = "",
        provider: str = "",
        duration_ms: float = 0.0,
    ) -> SensorResult:
        logger.warning("%s: %s (provider=%s)", self.name, reason, provider)
        return SensorResult(
            determined=False,
            chain=chain,
            method=method,
            outcome="malformed_response",
            reason=reason,
            duration_ms=duration_ms,
        )

    def __repr__(self) -> str:
        return f"PriceFeedSensor(name={self.name!r}, cached={len(self._cache)})"


__all__ = [
    "DEFAULT_CACHE_TTL",
    "DEFILLAMA_COINS_BASE",
    "HttpMarketClient",
    "MarketResponse",
    "PriceFeedSensor",
]
