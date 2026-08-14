"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for blockchain.transport -- rate limiting, caching and dispatch.

No test here touches the network. The dispatcher's adapter factory is
substituted with a scripted fake, so every provider response -- success,
error, 429, timeout -- is chosen by the test rather than by whichever public
endpoint happens to be up.

The clock is injected for the same reason. A rate limiter tested with real
sleeps is a slow test that still cannot reach the interesting states.
"""

from __future__ import annotations

import pytest

from blockchain.rpc.providers import default_catalog
from blockchain.rpc import (
    CallResult,
    ChainDispatcher,
    Outcome,
    RateLimiter,
    ResponseCache,
    Volatility,
    cache_key,
    resolve_volatility,
)
from config.rpc.chains import ChainName

NO_ENV: dict[str, str] = {}


class FakeClock:
    """Manually advanced monotonic clock."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeResponse:
    """Stands in for an AdapterResponse."""

    def __init__(self, ok: bool, data: object = None, error: object = None) -> None:
        self.ok = ok
        self.data = data
        self.error = error


class ScriptedAdapter:
    """
    Adapter that replays a scripted sequence of responses.

    Records every call so a test can assert what actually went out, which is
    the only way to tell a cache hit from a silent re-fetch.
    """

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, object]] = []

    def execute(self, request: object) -> FakeResponse:
        method = getattr(request, "method", "")
        params = getattr(request, "params", {})
        self.calls.append((method, params))
        if self._responses:
            return self._responses.pop(0)
        return FakeResponse(True, data="0x1")


def build_dispatcher(
    responses_by_provider: dict[str, list[FakeResponse]] | None = None,
    *,
    default: FakeResponse | None = None,
    clock: FakeClock | None = None,
    **kwargs: object,
) -> tuple[ChainDispatcher, dict[str, ScriptedAdapter]]:
    """
    A dispatcher whose adapters are scripted per provider.

    Everything above the adapter -- catalog, endpoint ordering, rate limiter,
    cache, circuit breaker -- is the real implementation.
    """
    clock = clock or FakeClock()
    dispatcher = ChainDispatcher(
        environ=NO_ENV,
        limiter=RateLimiter(clock=clock),
        cache=ResponseCache(clock=clock),
        **kwargs,  # type: ignore[arg-type]
    )

    adapters: dict[str, ScriptedAdapter] = {}
    scripts = responses_by_provider or {}

    def _adapter_for(endpoint, url):  # type: ignore[no-untyped-def]
        if url not in adapters:
            script = list(scripts.get(endpoint.provider, []))
            if not script and default is not None:
                script = [default]
            adapters[url] = ScriptedAdapter(script)
        adapters[url].provider = endpoint.provider  # type: ignore[attr-defined]
        return adapters[url]

    dispatcher._adapter_for = _adapter_for  # type: ignore[assignment]
    return dispatcher, adapters


# ==============================================================================
# RATE LIMITER
# ==============================================================================

def test_budget_is_spent_then_refused():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, safety_factor=1.0)
    limiter.register("p", 60)

    assert all(limiter.try_acquire("p") for _ in range(60))
    assert not limiter.try_acquire("p")


def test_budget_refills_over_the_window():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, safety_factor=1.0)
    limiter.register("p", 60)
    for _ in range(60):
        limiter.try_acquire("p")

    clock.advance(30.0)  # half a window
    granted = sum(1 for _ in range(40) if limiter.try_acquire("p"))
    assert 28 <= granted <= 30


def test_safety_factor_leaves_headroom():
    """
    Published ceilings are enforced with burst detection A01 cannot see, so
    spending the documented figure exactly is what triggers the 429.
    """
    limiter = RateLimiter(clock=FakeClock(), safety_factor=0.8)
    limiter.register("p", 100)
    granted = sum(1 for _ in range(100) if limiter.try_acquire("p"))
    assert granted == 80


def test_a_429_throttles_beyond_the_documented_limit():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, penalty_seconds=90.0)
    limiter.register("p", 600)

    assert limiter.try_acquire("p")
    limiter.penalise("p")

    assert not limiter.try_acquire("p")
    clock.advance(89.0)
    assert not limiter.try_acquire("p")
    clock.advance(2.0)
    assert limiter.try_acquire("p")


def test_retry_after_is_honoured_only_when_it_is_longer():
    """A Retry-After of 1s after a 429 is not a reason to resume immediately."""
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, penalty_seconds=90.0)
    limiter.register("p", 600)

    limiter.penalise("p", retry_after_seconds=1.0)
    clock.advance(2.0)
    assert not limiter.try_acquire("p"), "short Retry-After shortened the penalty"

    limiter.reset("p")
    limiter.penalise("p", retry_after_seconds=300.0)
    clock.advance(100.0)
    assert not limiter.try_acquire("p"), "long Retry-After was ignored"


def test_unregistered_provider_is_not_gated():
    limiter = RateLimiter(clock=FakeClock())
    assert limiter.try_acquire("never-registered")


def test_re_registering_does_not_refill_a_throttled_provider():
    """Rebuilding a dispatcher must not hand back an allowance not yet earned."""
    limiter = RateLimiter(clock=FakeClock())
    limiter.register("p", 60)
    limiter.penalise("p")

    limiter.register("p", 60)
    assert not limiter.try_acquire("p")


# ==============================================================================
# CACHE TTL POLICY
# ==============================================================================

def test_head_queries_are_barely_cached():
    assert resolve_volatility("eth_blockNumber") == Volatility.HEAD


def test_receipts_are_immutable():
    assert resolve_volatility("eth_getTransactionReceipt", ["0xabc"]) == Volatility.IMMUTABLE


def test_latest_balance_is_volatile():
    assert resolve_volatility("eth_getBalance", ["0xaddr", "latest"]) == Volatility.VOLATILE


def test_balance_at_a_buried_block_is_immutable():
    """
    What makes historical work affordable: a backtest re-reading the same old
    window pays for it once.
    """
    volatility = resolve_volatility(
        "eth_getBalance", ["0xaddr", hex(1000)], head_block=5000, confirmations=12
    )
    assert volatility == Volatility.IMMUTABLE


def test_balance_at_a_shallow_block_stays_volatile():
    """Inside the reorg window the answer can still change."""
    volatility = resolve_volatility(
        "eth_getBalance", ["0xaddr", hex(4995)], head_block=5000, confirmations=12
    )
    assert volatility == Volatility.VOLATILE


def test_confirmation_depth_comes_from_the_chain():
    """Polygon needs 128 confirmations where Ethereum needs 12."""
    params = ["0xaddr", hex(4950)]
    assert resolve_volatility(params=params, method="eth_getBalance",
                              head_block=5000, confirmations=12) == Volatility.IMMUTABLE
    assert resolve_volatility(params=params, method="eth_getBalance",
                              head_block=5000, confirmations=128) == Volatility.VOLATILE


def test_pending_is_never_treated_as_final():
    assert resolve_volatility("eth_getBalance", ["0xaddr", "pending"]) == Volatility.VOLATILE


# -- block tag extraction ---------------------------------------------------
#
# Regression set. The tag was originally found by scanning params forwards for
# anything 0x-prefixed, which finds the address first and tries to read it as
# a block number. Every method that takes a tag takes it last.

REAL_ADDRESS = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
REAL_TX_HASH = "0x" + "ab" * 32


def test_address_is_not_mistaken_for_a_block_tag():
    volatility = resolve_volatility(
        "eth_getBalance", [REAL_ADDRESS, hex(1000)], head_block=5000, confirmations=12
    )
    assert volatility == Volatility.IMMUTABLE


def test_call_with_no_block_tag_stays_volatile():
    """No tag means latest, which is never safe to hold."""
    volatility = resolve_volatility(
        "eth_getBalance", [REAL_ADDRESS], head_block=5000, confirmations=12
    )
    assert volatility == Volatility.VOLATILE


def test_trailing_bool_does_not_hide_the_tag():
    """eth_getBlockByNumber takes (tag, fullTx), so the tag is not last."""
    volatility = resolve_volatility(
        "eth_getBlockByNumber", [hex(1000), False], head_block=5000, confirmations=12
    )
    assert volatility == Volatility.IMMUTABLE


def test_transaction_hash_is_not_read_as_a_block_number():
    """A 66-character hash is far too long to be a block tag."""
    volatility = resolve_volatility(
        "eth_getLogs", [REAL_TX_HASH], head_block=5000, confirmations=12
    )
    assert volatility == Volatility.VOLATILE


def test_unknown_method_defaults_to_volatile():
    """A short cache costs a request; a long one costs a wrong answer."""
    assert resolve_volatility("eth_someMethodAddedLater", []) == Volatility.VOLATILE


# ==============================================================================
# CACHE BEHAVIOUR
# ==============================================================================

def test_cached_none_is_a_hit_not_a_miss():
    """
    eth_getTransactionReceipt returns null for an unmined hash. Collapsing
    that into a miss re-queries on every call.
    """
    cache = ResponseCache(clock=FakeClock())
    cache.put("k", None, Volatility.STABLE)
    found, value = cache.get("k")
    assert found is True
    assert value is None


def test_entries_expire():
    clock = FakeClock()
    cache = ResponseCache(clock=clock)
    cache.put("k", "v", Volatility.VOLATILE)  # 30s

    assert cache.get("k")[0]
    clock.advance(31.0)
    assert not cache.get("k")[0]


def test_never_class_is_not_stored():
    cache = ResponseCache(clock=FakeClock())
    cache.put("k", "v", Volatility.NEVER)
    assert not cache.get("k")[0]


def test_cache_key_ignores_the_endpoint_but_not_the_chain():
    """
    Two providers answering the same question share an entry; two chains
    never do.
    """
    assert cache_key("ethereum", "eth_getBalance", ["0xa"]) == cache_key(
        "ethereum", "eth_getBalance", ["0xa"]
    )
    assert cache_key("ethereum", "eth_getBalance", ["0xa"]) != cache_key(
        "polygon", "eth_getBalance", ["0xa"]
    )


def test_lru_eviction_is_bounded():
    cache = ResponseCache(max_entries=3, clock=FakeClock())
    for i in range(5):
        cache.put(f"k{i}", i, Volatility.STABLE)
    assert len(cache) == 3
    assert not cache.get("k0")[0]
    assert cache.get("k4")[0]


def test_chain_invalidation_is_scoped():
    cache = ResponseCache(clock=FakeClock())
    cache.put(cache_key("ethereum", "m", []), 1, Volatility.STABLE)
    cache.put(cache_key("polygon", "m", []), 2, Volatility.STABLE)

    assert cache.invalidate_chain("ethereum") == 1
    assert cache.get(cache_key("polygon", "m", []))[0]


def test_cache_records_the_asserting_provider():
    """Evidence provenance must name who said it, not who was selected later."""
    cache = ResponseCache(clock=FakeClock())
    key = cache_key("ethereum", "m", [])
    cache.put(key, 1, Volatility.STABLE, provider="llamarpc")
    assert cache.provider_for(key) == "llamarpc"


# ==============================================================================
# DISPATCH
# ==============================================================================

def test_successful_call_carries_provenance():
    dispatcher, _ = build_dispatcher(default=FakeResponse(True, data="0x10"))
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert result.outcome == Outcome.OK
    assert result.determined
    assert result.value == "0x10"
    assert result.provider
    assert result.provenance()["source"] == result.provider


def test_provenance_never_carries_the_endpoint_url():
    """A keyed URL holds the credential in its path, and evidence is written to disk."""
    dispatcher, _ = build_dispatcher(default=FakeResponse(True, data="0x1"))
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")
    assert "http" not in str(result.provenance())


def test_failure_falls_over_to_the_next_provider():
    catalog = default_catalog()
    first, second = catalog.available(ChainName.ETHEREUM, environ=NO_ENV)[:2]

    dispatcher, _ = build_dispatcher(
        {
            first.provider: [FakeResponse(False, error="connection refused")],
            second.provider: [FakeResponse(True, data="0x99")],
        }
    )
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert result.outcome == Outcome.OK
    assert result.value == "0x99"
    assert result.provider == second.provider
    assert result.failures[0][0] == first.provider


def test_total_failure_is_undetermined_not_empty():
    """
    The distinction the whole module exists for. An empty result that reads
    like a clean negative is how a network failure becomes a finding.
    """
    dispatcher, _ = build_dispatcher(default=FakeResponse(False, error="boom"))
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert result.outcome == Outcome.ALL_ENDPOINTS_FAILED
    assert result.determined is False
    assert result.value is None
    assert result.reason


def test_attempts_are_bounded():
    dispatcher, _ = build_dispatcher(default=FakeResponse(False, error="boom"), max_attempts=2)
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")
    assert result.attempts == 2


def test_a_429_penalises_that_provider():
    catalog = default_catalog()
    first = catalog.available(ChainName.ETHEREUM, environ=NO_ENV)[0]

    dispatcher, _ = build_dispatcher(
        {first.provider: [FakeResponse(False, error="HTTP 429 Too Many Requests")]},
        default=FakeResponse(True, data="0x1"),
    )
    dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert first.provider in dispatcher.limiter.throttled_providers()


def test_second_identical_call_is_served_from_cache():
    dispatcher, adapters = build_dispatcher(
        default=FakeResponse(True, data="0xdeadbeef"),
    )
    params = ["0xabc"]
    first = dispatcher.call(ChainName.ETHEREUM, "eth_getTransactionReceipt", params)
    second = dispatcher.call(ChainName.ETHEREUM, "eth_getTransactionReceipt", params)

    assert first.outcome == Outcome.OK
    assert second.outcome == Outcome.CACHED
    assert second.from_cache
    assert second.value == first.value

    dispatched = sum(len(a.calls) for a in adapters.values())
    assert dispatched == 1, "cache hit still went to the network"


def test_failures_are_never_cached():
    """A 429 says something about the provider, not about the chain."""
    dispatcher, adapters = build_dispatcher(default=FakeResponse(False, error="boom"))
    dispatcher.call(ChainName.ETHEREUM, "eth_getTransactionReceipt", ["0xabc"])
    dispatcher.call(ChainName.ETHEREUM, "eth_getTransactionReceipt", ["0xabc"])

    dispatched = sum(len(a.calls) for a in adapters.values())
    assert dispatched > 1, "a failure was cached"


# ==============================================================================
# SPEND REPORTING
# ==============================================================================

def test_a_successful_call_reports_one_request_to_its_provider():
    spends: list[tuple[str, str, int]] = []
    dispatcher, _ = build_dispatcher(
        default=FakeResponse(True, data="0x1"),
        on_spend=lambda chain, provider, calls: spends.append((chain, provider, calls)),
    )
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert spends == [("ethereum", result.provider, 1)]


def test_a_failed_call_is_still_spent():
    """
    The reason the count is taken before the response. A provider meters the
    request on arrival, so counting only what came back would undercount
    precisely during the retry storms that burn the most allowance.
    """
    spends: list[tuple[str, str, int]] = []
    dispatcher, _ = build_dispatcher(
        default=FakeResponse(False, error="boom"),
        max_attempts=2,
        on_spend=lambda chain, provider, calls: spends.append((chain, provider, calls)),
    )
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert result.determined is False
    assert sum(calls for _, _, calls in spends) == 2 == result.attempts


def test_spend_is_attributed_per_provider_not_lumped_together():
    catalog = default_catalog()
    first, second = catalog.available(ChainName.ETHEREUM, environ=NO_ENV)[:2]

    dispatcher, _ = build_dispatcher(
        {
            first.provider: [FakeResponse(False, error="connection refused")],
            second.provider: [FakeResponse(True, data="0x99")],
        }
    )
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert result.provider_attempts == ((first.provider, 1), (second.provider, 1))


def test_a_locally_throttled_provider_is_never_charged():
    """
    The one outcome that must not reach a ledger. The local limiter refused
    before anything left the process, so the provider never saw a request --
    charging for it would make throttling look like usage and close a budget on
    a chain that was never read.
    """
    catalog = default_catalog()
    first = catalog.available(ChainName.ETHEREUM, environ=NO_ENV)[0]

    dispatcher, _ = build_dispatcher(default=FakeResponse(True, data="0x1"))
    dispatcher.limiter.penalise(first.provider)
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    charged = dict(result.provider_attempts)
    assert first.provider not in charged
    assert any(provider for provider in charged), "nothing was dispatched at all"
    assert first.provider in dict(result.failures)


def test_every_candidate_throttled_spends_nothing():
    catalog = default_catalog()
    spends: list[tuple[str, str, int]] = []

    dispatcher, _ = build_dispatcher(
        default=FakeResponse(True, data="0x1"),
        on_spend=lambda chain, provider, calls: spends.append((chain, provider, calls)),
    )
    for endpoint in catalog.available(ChainName.ETHEREUM, environ=NO_ENV):
        dispatcher.limiter.penalise(endpoint.provider)

    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert result.outcome == Outcome.BUDGET_EXHAUSTED
    assert result.provider_attempts == ()
    assert spends == []


def test_a_cache_hit_spends_nothing():
    spends: list[tuple[str, str, int]] = []
    dispatcher, _ = build_dispatcher(
        default=FakeResponse(True, data="0xdeadbeef"),
        on_spend=lambda chain, provider, calls: spends.append((chain, provider, calls)),
    )
    params = ["0xabc"]
    dispatcher.call(ChainName.ETHEREUM, "eth_getTransactionReceipt", params)
    second = dispatcher.call(ChainName.ETHEREUM, "eth_getTransactionReceipt", params)

    assert second.outcome == Outcome.CACHED
    assert len(spends) == 1, "a cache hit was charged to a provider"


def test_a_refused_capability_spends_nothing():
    spends: list[tuple[str, str, int]] = []
    dispatcher, _ = build_dispatcher(
        default=FakeResponse(True, data="0x1"),
        on_spend=lambda chain, provider, calls: spends.append((chain, provider, calls)),
    )
    dispatcher.call(
        ChainName.ETHEREUM, "eth_getBalance", ["0xabc", "0x10"], require_archive=True
    )
    assert spends == []


def test_a_broken_sink_does_not_lose_the_answer():
    """
    The answer is already in hand when the sink runs. Losing a chain read to a
    bookkeeping failure would be the worse trade, so the sink's exception is
    logged and the result stands.
    """
    def explode(chain: str, provider: str, calls: int) -> None:
        raise RuntimeError("ledger is on fire")

    dispatcher, _ = build_dispatcher(
        default=FakeResponse(True, data="0x10"), on_spend=explode
    )
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")

    assert result.outcome == Outcome.OK
    assert result.value == "0x10"


def test_no_sink_is_a_supported_configuration():
    """A dispatcher with nowhere to report to still dispatches."""
    dispatcher, _ = build_dispatcher(default=FakeResponse(True, data="0x1"))
    result = dispatcher.call(ChainName.ETHEREUM, "eth_blockNumber")
    assert result.outcome == Outcome.OK
    assert result.provider_attempts


# ==============================================================================
# CAPABILITY GATING
# ==============================================================================

def test_archive_request_is_refused_rather_than_silently_downgraded():
    """
    A non-archive endpoint asked for historical state may return the latest
    value instead of erroring -- a wrong answer wearing the costume of a right
    one. So the check happens before dispatch.
    """
    dispatcher, adapters = build_dispatcher(default=FakeResponse(True, data="0x1"))
    result = dispatcher.call(
        ChainName.ETHEREUM, "eth_getBalance", ["0xabc", "0x10"], require_archive=True
    )

    assert result.outcome == Outcome.CAPABILITY_UNAVAILABLE
    assert result.determined is False
    assert not adapters, "a request went out despite the missing capability"


def test_capability_refusal_names_the_missing_credential():
    dispatcher, _ = build_dispatcher(default=FakeResponse(True, data="0x1"))
    result = dispatcher.call(ChainName.ETHEREUM, "eth_getBalance", [], require_archive=True)
    assert "ALCHEMY_API_KEY" in result.reason


def test_archive_is_reported_unavailable_on_evm_without_a_key():
    dispatcher, _ = build_dispatcher(default=FakeResponse(True))
    assert dispatcher.supports_archive(ChainName.ETHEREUM) is False

    report = dispatcher.capability_report(ChainName.ETHEREUM)
    assert report["reachable"] is True
    assert report["archive"] is False
    assert report["archive_unlocked_by"]


def test_bitcoin_reports_archive_without_a_key():
    """Esplora is archival by nature, so BTC history is free-tier reachable."""
    dispatcher, _ = build_dispatcher(default=FakeResponse(True))
    assert dispatcher.supports_archive(ChainName.BITCOIN) is True


def test_archive_becomes_available_once_keyed():
    dispatcher = ChainDispatcher(environ={"ALCHEMY_API_KEY": "k"})
    assert dispatcher.supports_archive(ChainName.ETHEREUM) is True


# ==============================================================================
# REPORTING
# ==============================================================================

def test_health_snapshot_is_json_safe_and_secret_free():
    dispatcher = ChainDispatcher(environ={"ALCHEMY_API_KEY": "LEAKME"})
    import json

    rendered = json.dumps(dispatcher.health(), default=str)
    assert "LEAKME" not in rendered


def test_call_result_as_dict_is_serialisable():
    result = CallResult(outcome=Outcome.OK, value=1, provider="p", chain="ethereum")
    import json

    assert json.loads(json.dumps(result.as_dict()))["determined"] is True
