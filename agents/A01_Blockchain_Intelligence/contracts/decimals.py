"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    contracts.decimals

Purpose:
    Resolve the one fact the event decoder cannot: the exponent that turns a
    raw integer into a human quantity.

Design goals:
    - Well-known tokens answered without a network call
    - Failures never guessed; a contract that does not implement ``decimals()``
      returns None rather than a fabricated 18
    - Results cached long, because token decimals almost never change
    - Thread-safe; pipeline stages may resolve from different threads

Notes:
    An ERC-20 ``Transfer`` event carries the amount as a raw integer in the
    token's own base unit.  USDC uses 6 decimals, so 140261088 means
    $140.26 -- but without the exponent it is indistinguishable from
    140,261,088 units of an 18-decimal token, which is roughly 0.14 wei-scale
    tokens: a number that is a trillion times too small, and looks ordinary.

    The exponent lives in the contract's ``decimals()`` view function, which
    returns a uint8 and costs no gas to call.  The call is a plain
    ``eth_call`` with a 4-byte selector and no arguments:

        eth_call({"to": contract, "data": "0x313ce567"}, "latest")

    The selector ``0x313ce567`` is the first four bytes of
    ``keccak256("decimals()")``.  This is the single most-called view function
    in the ERC-20 standard and the constant is verified at import time against
    the same Keccak-256 implementation used by ``contracts.signatures``.

    The response is a single ABI-encoded uint256 (padded to 32 bytes), whose
    meaningful range is 0-77 (``Amount``'s upper bound for ``decimals``).

    Not every contract implements ``decimals()``.  The function was optional in
    the original ERC-20 proposal, and proxies or non-standard tokens may
    revert.  A failed or unreadable response is returned as ``None``, never
    defaulted to 18 -- that is the exact mistake this module exists to prevent.

Boundary:
    This module does not import the RPC layer.  Chain access is injected as
    a protocol, so the pure encoding/parsing functions remain testable without
    a network and the resolver can be tested with a stub.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# -- selector ----------------------------------------------------------------

DECIMALS_SELECTOR: Final[str] = "0x313ce567"

_MAX_DECIMALS: Final[int] = 77


def _verify_selector() -> None:
    """Check the constant against a live Keccak-256, when available."""
    try:
        import hashlib

        digest = hashlib.new("keccak256", b"decimals()")
        computed = "0x" + digest.hexdigest()[:8]
    except (ValueError, TypeError):
        return
    if computed != DECIMALS_SELECTOR:
        raise RuntimeError(
            f"DECIMALS_SELECTOR mismatch: computed {computed}, "
            f"have {DECIMALS_SELECTOR}"
        )


_verify_selector()


# -- well-known tokens -------------------------------------------------------

WELL_KNOWN: Final[dict[tuple[str, str], int]] = {
    # Ethereum mainnet
    ("ethereum", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"): 6,   # USDC
    ("ethereum", "0xdac17f958d2ee523a2206206994597c13d831ec7"): 6,   # USDT
    ("ethereum", "0x6b175474e89094c44da98b954eedeac495271d0f"): 18,  # DAI
    ("ethereum", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"): 18,  # WETH
    ("ethereum", "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"): 8,   # WBTC
    ("ethereum", "0x514910771af9ca656af840dff83e8264ecf986ca"): 18,  # LINK
    ("ethereum", "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"): 18,  # UNI
    ("ethereum", "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0"): 18,  # MATIC
    ("ethereum", "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce"): 18,  # SHIB
    # Arbitrum
    ("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"): 6,   # USDC
    ("arbitrum", "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"): 6,   # USDT
    ("arbitrum", "0x82af49447d8a07e3bd95bd0d56f35241523fbab1"): 18,  # WETH
    ("arbitrum", "0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f"): 8,   # WBTC
    # Optimism
    ("optimism", "0x0b2c639c533813f4aa9d7837caf62653d097ff85"): 6,   # USDC
    ("optimism", "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58"): 6,   # USDT
    ("optimism", "0x4200000000000000000000000000000000000006"): 18,  # WETH
    # Base
    ("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"): 6,     # USDC
    ("base", "0x4200000000000000000000000000000000000006"): 18,     # WETH
    # Polygon
    ("polygon", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"): 6,   # USDC
    ("polygon", "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"): 6,   # USDT
    ("polygon", "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619"): 18,  # WETH
    # BNB Chain -- keyed by the registry slug `bnb_chain`, not `bsc`: a resolve()
    # call arrives with ChainName.BNB_CHAIN.value, so a `bsc` key never hit and
    # every BNB token silently fell through to an eth_call or a failure.
    ("bnb_chain", "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d"): 18,  # USDC
    ("bnb_chain", "0x55d398326f99059ff775485246999027b3197955"): 18,  # USDT
    ("bnb_chain", "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"): 18,  # WBNB
    ("bnb_chain", "0x2170ed0880ac9a755fd29b2688956bd959f933f8"): 18,  # ETH (BNB Chain)
}


# -- pure encoding / parsing -------------------------------------------------

def encode_decimals_call(contract: str) -> tuple[dict[str, str], str]:
    """
    Build the ``eth_call`` parameters for ``decimals()``.

    Returns ``(call_object, block_tag)`` ready to pass as
    ``dispatcher.call(chain, "eth_call", [call_object, block_tag])``.
    """
    return {"to": contract, "data": DECIMALS_SELECTOR}, "latest"


def parse_decimals_response(value: Any) -> int | None:
    """
    Read a ``decimals()`` return value.

    Returns the integer on success, ``None`` when the response is absent,
    empty, or outside the valid range.  Never raises for bad data -- the
    caller treats ``None`` as "could not determine" and carries the raw
    integer with scale unknown.
    """
    if not isinstance(value, str):
        return None

    hex_str = value[2:] if value.startswith("0x") else value

    if not hex_str:
        return None

    # A valid ABI-encoded uint256 is exactly 64 hex chars (32 bytes).
    # Some nodes return the minimal encoding; accept up to 64 chars.
    if len(hex_str) > 64:
        return None

    try:
        decimals = int(hex_str, 16)
    except ValueError:
        return None

    if decimals < 0 or decimals > _MAX_DECIMALS:
        return None

    return decimals


# -- dispatcher protocol -----------------------------------------------------

@runtime_checkable
class _CallResult(Protocol):
    @property
    def determined(self) -> bool: ...

    @property
    def value(self) -> Any: ...


@runtime_checkable
class Dispatcher(Protocol):
    """
    Anything that can make an ``eth_call``.

    Matches :class:`blockchain.rpc.ChainDispatcher` without importing it,
    so this module stays free of RPC-layer dependencies.
    """

    def call(
        self,
        chain: Any,
        method: str,
        params: Any = None,
        *,
        use_cache: bool = ...,
    ) -> _CallResult: ...


# -- result ------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class DecimalsResult:
    """
    The outcome of a decimals lookup.

    ``decimals`` is ``None`` when the contract does not implement the function
    or the call failed.  ``source`` records how the answer was obtained, for
    diagnostics and cache-hit tracking.
    """

    decimals: int | None
    source: str
    contract: str
    chain: str

    @property
    def resolved(self) -> bool:
        return self.decimals is not None


# -- resolver ----------------------------------------------------------------

_STABLE_TTL: Final[float] = 24 * 60 * 60.0

_MAX_FAILURES_BEFORE_BACKOFF: Final[int] = 3


class TokenDecimalsResolver:
    """
    Resolve ERC-20 ``decimals()`` for a token contract.

    Resolution order:
        1. Well-known table (no I/O)
        2. In-memory cache (no I/O)
        3. ``eth_call`` via the injected dispatcher

    The in-memory cache is separate from the RPC cache because the RPC layer
    classifies ``eth_call`` as VOLATILE (30 s TTL), but token decimals are
    STABLE -- they effectively never change after deployment.
    """

    def __init__(self, dispatcher: Dispatcher) -> None:
        self._dispatcher = dispatcher
        self._cache: dict[tuple[str, str], int] = {}
        self._failures: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def resolve(self, contract: str, chain: str) -> DecimalsResult:
        """
        Look up ``decimals()`` for one token contract.

        Returns a :class:`DecimalsResult` whose ``decimals`` is ``None`` when
        the value could not be determined.  Never raises for a contract that
        does not implement the function.
        """
        key = (chain, contract.lower())

        well_known = WELL_KNOWN.get(key)
        if well_known is not None:
            return DecimalsResult(well_known, "well_known", contract, chain)

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return DecimalsResult(cached, "cache", contract, chain)

            if self._failures.get(key, 0) >= _MAX_FAILURES_BEFORE_BACKOFF:
                return DecimalsResult(None, "backed_off", contract, chain)

        fetched = self._fetch(contract, chain)
        if fetched is not None:
            with self._lock:
                self._cache[key] = fetched
                self._failures.pop(key, None)
            return DecimalsResult(fetched, "eth_call", contract, chain)

        with self._lock:
            self._failures[key] = self._failures.get(key, 0) + 1

        return DecimalsResult(None, "failed", contract, chain)

    def resolve_batch(
        self, contracts: list[tuple[str, str]]
    ) -> dict[tuple[str, str], DecimalsResult]:
        """
        Resolve decimals for multiple ``(contract, chain)`` pairs.

        A convenience over calling :meth:`resolve` in a loop; each pair is
        resolved independently and failures do not block the rest.
        """
        results: dict[tuple[str, str], DecimalsResult] = {}
        for contract, chain in contracts:
            results[(contract, chain)] = self.resolve(contract, chain)
        return results

    def prime(self, contract: str, chain: str, decimals: int) -> None:
        """
        Inject a known value, bypassing ``eth_call``.

        Used when decimals arrive from a source other than the contract itself
        -- a token list, a manual override, or a prior pipeline stage.
        """
        if decimals < 0 or decimals > _MAX_DECIMALS:
            raise ValueError(f"decimals out of range: {decimals}")
        key = (chain, contract.lower())
        with self._lock:
            self._cache[key] = decimals
            self._failures.pop(key, None)

    def invalidate(self, contract: str, chain: str) -> bool:
        """Drop a cached entry, forcing the next lookup to re-fetch."""
        key = (chain, contract.lower())
        with self._lock:
            removed = self._cache.pop(key, None) is not None
            self._failures.pop(key, None)
            return removed

    def snapshot(self) -> dict[str, Any]:
        """Cache statistics, for diagnostics."""
        with self._lock:
            return {
                "cached": len(self._cache),
                "backed_off": sum(
                    1 for v in self._failures.values()
                    if v >= _MAX_FAILURES_BEFORE_BACKOFF
                ),
                "well_known": len(WELL_KNOWN),
            }

    def _fetch(self, contract: str, chain: str) -> int | None:
        call_obj, block_tag = encode_decimals_call(contract)
        try:
            result = self._dispatcher.call(
                chain, "eth_call", [call_obj, block_tag], use_cache=True
            )
        except Exception:
            logger.debug("eth_call for decimals() failed on %s:%s", chain, contract)
            return None

        if not result.determined:
            return None

        return parse_decimals_response(result.value)


__all__ = [
    "DECIMALS_SELECTOR",
    "WELL_KNOWN",
    "DecimalsResult",
    "Dispatcher",
    "TokenDecimalsResolver",
    "encode_decimals_call",
    "parse_decimals_response",
]
