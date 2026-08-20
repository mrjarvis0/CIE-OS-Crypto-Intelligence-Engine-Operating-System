"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for the price feed sensor -- USD spot pricing, caching, and the
determined/undetermined distinction.

No test here touches the network.  Every read is served by a scripted
client, because a price sensor that depends on a live API tests the
provider's uptime rather than the sensor.
"""

from __future__ import annotations

import pytest

from sensors.envelope import RecordKind, content_id
from sensors.market.price_sensor import (
    MarketResponse,
    PriceFeedSensor,
    _CHAIN_TO_LLAMA,
    _CHAIN_TO_NATIVE_CGID,
)


class ScriptedMarketClient:
    """
    A MarketClient stand-in that answers from a script.

    Records every call so a test can assert not only what came back but
    what URL was asked -- the chain mapping and coin key are only
    observable in the request.
    """

    def __init__(self, responses: dict[str, MarketResponse] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []

    def get(self, url: str, *, provider: str) -> MarketResponse:
        self.calls.append((url, provider))
        for pattern, resp in self.responses.items():
            if pattern in url:
                return resp
        return MarketResponse(
            ok=False, body=None, provider=provider, duration_ms=0.1,
            reason="no scripted response",
        )


def llama_response(
    coin_key: str, price: float, symbol: str = "ETH", **extra: object,
) -> MarketResponse:
    """Build a DefiLlama-coins response for one coin."""
    entry: dict[str, object] = {
        "price": price, "symbol": symbol,
        "timestamp": 1_700_000_000, "confidence": 0.99,
    }
    entry.update(extra)
    return MarketResponse(
        ok=True,
        body={"coins": {coin_key: entry}},
        provider="defillama-coins",
        duration_ms=42.0,
    )


def sensor_with(
    responses: dict[str, MarketResponse],
) -> tuple[PriceFeedSensor, ScriptedMarketClient]:
    client = ScriptedMarketClient(responses)
    sensor = PriceFeedSensor(client=client, cache_ttl=5)
    return sensor, client


# ==============================================================================
# NATIVE PRICE
# ==============================================================================

def test_native_price_returns_usd_with_provenance():
    sensor, _ = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    result = sensor.native_price("ethereum")

    assert result.ok
    record = result.unwrap()
    assert record.kind is RecordKind.PRICE
    assert record.payload["price_usd"] == 2345.67
    assert record.payload["symbol"] == "ETH"
    assert record.payload["chain"] == "ethereum"
    assert record.provenance.provider == "defillama-coins"


def test_native_price_bitcoin():
    sensor, _ = sensor_with({
        "coingecko:bitcoin": llama_response("coingecko:bitcoin", 65000.0, "BTC"),
    })
    result = sensor.native_price("bitcoin")

    assert result.ok
    assert result.unwrap().payload["price_usd"] == 65000.0
    assert result.unwrap().payload["symbol"] == "BTC"


def test_native_price_l2_chains_share_eth():
    """Arbitrum, Optimism, Base all have ETH as native asset."""
    sensor, _ = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    for chain in ("arbitrum", "optimism", "base", "linea", "scroll"):
        sensor._cache.clear()
        result = sensor.native_price(chain)
        assert result.ok, f"{chain} should resolve to ETH price"
        assert result.unwrap().payload["price_usd"] == 2345.67


def test_native_price_unmapped_chain_is_undetermined():
    sensor, _ = sensor_with({})
    result = sensor.native_price("unknown_chain")

    assert not result.determined
    assert "no native-asset identifier" in result.reason


def test_native_price_failure_is_undetermined():
    """A transport failure must not read as 'the asset has no price'."""
    sensor, _ = sensor_with({})
    result = sensor.native_price("ethereum")

    assert not result.determined
    assert result.record is None


def test_native_price_zero_is_valid():
    """A zero price is a finding, not a failure."""
    sensor, _ = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 0.0, "ETH"),
    })
    result = sensor.native_price("ethereum")

    assert result.ok
    assert result.unwrap().payload["price_usd"] == 0.0


def test_native_price_rejects_empty_chain():
    sensor, _ = sensor_with({})
    with pytest.raises(ValueError):
        sensor.native_price("")


def test_native_price_normalises_chain_name():
    sensor, _ = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    result = sensor.native_price("  Ethereum  ")

    assert result.ok
    assert result.unwrap().payload["chain"] == "ethereum"


# ==============================================================================
# TOKEN PRICE
# ==============================================================================

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"


def test_token_price_returns_usd_with_contract():
    sensor, _ = sensor_with({
        f"ethereum:{USDC}": llama_response(f"ethereum:{USDC}", 1.0, "USDC"),
    })
    result = sensor.token_price("ethereum", USDC)

    assert result.ok
    record = result.unwrap()
    assert record.payload["price_usd"] == 1.0
    assert record.payload["contract"] == USDC
    assert record.payload["chain"] == "ethereum"


def test_token_price_bsc_chain_maps_correctly():
    """bnb_chain maps to DefiLlama's 'bsc' platform identifier."""
    token = "0x" + "bb" * 20
    sensor, client = sensor_with({
        f"bsc:{token}": llama_response(f"bsc:{token}", 5.0, "CAKE"),
    })
    result = sensor.token_price("bnb_chain", token)

    assert result.ok
    assert result.unwrap().payload["price_usd"] == 5.0
    assert "bsc:" in client.calls[0][0]


def test_token_price_unmapped_chain_is_undetermined():
    sensor, _ = sensor_with({})
    result = sensor.token_price("bitcoin", "some_address")

    assert not result.determined
    assert "no DefiLlama platform" in result.reason


def test_token_price_failure_is_undetermined():
    sensor, _ = sensor_with({})
    result = sensor.token_price("ethereum", USDC)

    assert not result.determined


def test_token_price_rejects_empty_contract():
    sensor, _ = sensor_with({})
    with pytest.raises(ValueError):
        sensor.token_price("ethereum", "")


def test_token_price_rejects_empty_chain():
    sensor, _ = sensor_with({})
    with pytest.raises(ValueError):
        sensor.token_price("", USDC)


def test_token_price_lowercases_contract():
    mixed = "0xA0B86991C6218B36C1D19D4A2E9EB0CE3606EB48"
    sensor, client = sensor_with({
        f"ethereum:{mixed.lower()}": llama_response(
            f"ethereum:{mixed.lower()}", 1.0, "USDC",
        ),
    })
    result = sensor.token_price("ethereum", mixed)

    assert result.ok
    assert result.unwrap().payload["contract"] == mixed.lower()


# ==============================================================================
# RESPONSE PARSING
# ==============================================================================

def test_malformed_body_is_undetermined():
    client = ScriptedMarketClient({
        "coingecko:ethereum": MarketResponse(
            ok=True, body="not a dict", provider="defillama-coins",
            duration_ms=1.0,
        ),
    })
    sensor = PriceFeedSensor(client=client)
    result = sensor.native_price("ethereum")

    assert not result.determined
    assert result.outcome == "malformed_response"


def test_missing_coins_key_is_malformed():
    client = ScriptedMarketClient({
        "coingecko:ethereum": MarketResponse(
            ok=True, body={"no_coins": {}}, provider="defillama-coins",
            duration_ms=1.0,
        ),
    })
    sensor = PriceFeedSensor(client=client)
    result = sensor.native_price("ethereum")

    assert not result.determined
    assert result.outcome == "malformed_response"


def test_missing_coin_entry_is_undetermined():
    """Provider answered but has no price for this coin -- not malformed."""
    client = ScriptedMarketClient({
        "coingecko:ethereum": MarketResponse(
            ok=True, body={"coins": {}}, provider="defillama-coins",
            duration_ms=1.0,
        ),
    })
    sensor = PriceFeedSensor(client=client)
    result = sensor.native_price("ethereum")

    assert not result.determined
    assert "no price entry" in result.reason


def test_non_numeric_price_is_malformed():
    client = ScriptedMarketClient({
        "coingecko:ethereum": MarketResponse(
            ok=True,
            body={"coins": {"coingecko:ethereum": {
                "price": "not a number", "symbol": "ETH",
            }}},
            provider="defillama-coins",
            duration_ms=1.0,
        ),
    })
    sensor = PriceFeedSensor(client=client)
    result = sensor.native_price("ethereum")

    assert not result.determined
    assert result.outcome == "malformed_response"


# ==============================================================================
# CACHING
# ==============================================================================

def test_cache_returns_previous_result():
    sensor, client = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    first = sensor.native_price("ethereum")
    second = sensor.native_price("ethereum")

    assert first.ok and second.ok
    assert len(client.calls) == 1


def test_cache_expires_after_ttl():
    client = ScriptedMarketClient({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    sensor = PriceFeedSensor(client=client, cache_ttl=1)

    sensor.native_price("ethereum")
    assert len(client.calls) == 1

    for key in list(sensor._cache):
        ts, result = sensor._cache[key]
        sensor._cache[key] = (ts - 10, result)

    sensor.native_price("ethereum")
    assert len(client.calls) == 2


def test_cache_is_keyed_per_chain():
    """ETH price for ethereum and arbitrum are cached separately."""
    sensor, client = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    sensor.native_price("ethereum")
    sensor.native_price("arbitrum")

    assert len(client.calls) == 2


def test_cache_is_keyed_per_token():
    usdt = "0xdac17f958d2ee523a2206206994597c13d831ec7"
    sensor, client = sensor_with({
        f"ethereum:{USDC}": llama_response(f"ethereum:{USDC}", 1.0, "USDC"),
        f"ethereum:{usdt}": llama_response(f"ethereum:{usdt}", 1.0, "USDT"),
    })
    sensor.token_price("ethereum", USDC)
    sensor.token_price("ethereum", usdt)

    assert len(client.calls) == 2


# ==============================================================================
# ENVELOPE INTEGRATION
# ==============================================================================

def test_price_record_id_is_content_addressed():
    sensor, _ = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    record = sensor.native_price("ethereum").unwrap()

    expected = content_id("ethereum", RecordKind.PRICE, record.payload)
    assert record.record_id == expected


def test_price_record_kind_is_price():
    sensor, _ = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    record = sensor.native_price("ethereum").unwrap()
    assert record.kind is RecordKind.PRICE


def test_price_record_height_is_none():
    """Price is time-scoped, not height-scoped."""
    sensor, _ = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    record = sensor.native_price("ethereum").unwrap()
    assert record.height is None


def test_provenance_excludes_url():
    """Provenance carries the provider name, never the endpoint URL."""
    sensor, _ = sensor_with({
        "coingecko:ethereum": llama_response("coingecko:ethereum", 2345.67, "ETH"),
    })
    record = sensor.native_price("ethereum").unwrap()
    prov = record.provenance.as_dict()

    assert "url" not in prov
    assert "endpoint" not in prov
    assert prov["provider"] == "defillama-coins"


# ==============================================================================
# CHAIN MAPPINGS
# ==============================================================================

def test_every_supported_chain_has_native_mapping():
    """Every chain in the A01 registry should have a native price mapping."""
    from config.rpc.chains import supported_chain_names

    for name in supported_chain_names():
        assert name.value in _CHAIN_TO_NATIVE_CGID, (
            f"missing native-asset mapping for {name.value}"
        )


def test_every_evm_chain_has_token_mapping():
    """Every EVM chain should have a DefiLlama token platform mapping."""
    from config.rpc.chains import ChainType, get_chain, supported_chain_names

    for name in supported_chain_names():
        config = get_chain(name)
        if config.chain_type is ChainType.EVM:
            assert name.value in _CHAIN_TO_LLAMA, (
                f"missing DefiLlama token mapping for EVM chain {name.value}"
            )


# ==============================================================================
# HEALTH
# ==============================================================================

def test_health_reports_mapped_chains():
    sensor, _ = sensor_with({})
    health = sensor.health()

    assert "ethereum" in health["mapped_chains_native"]
    assert "ethereum" in health["mapped_chains_token"]
    assert health["cache_ttl"] == 5


# ==============================================================================
# CONSTRUCTION
# ==============================================================================

def test_negative_cache_ttl_is_rejected():
    with pytest.raises(ValueError):
        PriceFeedSensor(cache_ttl=-1)


def test_zero_cache_ttl_is_allowed():
    sensor = PriceFeedSensor(cache_ttl=0)
    assert sensor._cache_ttl == 0


def test_repr():
    sensor, _ = sensor_with({})
    assert "price_feed" in repr(sensor)
