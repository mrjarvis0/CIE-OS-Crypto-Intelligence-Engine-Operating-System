"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    blockchain.transport.cache

Purpose:
    Cache chain reads, with a lifetime that reflects how long the answer is
    actually true for.

Design goals:
    - Immutable results cached hard, head-dependent results barely at all
    - Reorg depth respected, not assumed
    - Failures never cached
    - Bounded memory
    - No network I/O

Notes:
    A single TTL would be wrong in both directions at once. Caching
    ``eth_blockNumber`` for a minute makes A01 reason about a stale head;
    re-fetching a ten-year-old block on every call burns a free-tier budget on
    an answer that cannot change.

    So lifetime is derived from the claim, not the clock. A finalized block is
    immutable and can be held indefinitely. A recent block can still be
    reorged out, and the depth at which that stops being a risk is already
    recorded per chain as ``ChainConfig.confirmations`` -- 12 on Ethereum, 128
    on Polygon, 6 on Bitcoin -- so that figure decides whether a result is
    finalized rather than a number invented here.

    Nothing that failed is ever cached. A 429 or a timeout says something
    about the provider, not about the chain, and caching it would turn one
    throttled second into minutes of fabricated emptiness.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Final

Clock = Callable[[], float]

#: Entries held before the least recently used is evicted.
DEFAULT_MAX_ENTRIES: Final[int] = 4096

#: Practically forever. Used for results that cannot change once finalized.
IMMUTABLE_TTL: Final[float] = 30 * 24 * 60 * 60.0


class Volatility(StrEnum):
    """How long a result stays true."""

    #: Cannot change: a finalized block, a receipt, historical state.
    IMMUTABLE = "immutable"
    #: Changes only on a contract event: token decimals, symbol, bytecode.
    STABLE = "stable"
    #: Changes every few blocks: balances, nonces, pool reserves.
    VOLATILE = "volatile"
    #: Changes constantly: chain head, gas price, mempool.
    HEAD = "head"
    #: Must not be cached at all.
    NEVER = "never"


#: Default lifetime per volatility class.
TTL_BY_VOLATILITY: Final[dict[Volatility, float]] = {
    Volatility.IMMUTABLE: IMMUTABLE_TTL,
    Volatility.STABLE: 60 * 60.0,
    Volatility.VOLATILE: 30.0,
    Volatility.HEAD: 5.0,
    Volatility.NEVER: 0.0,
}


#: Volatility of the EVM methods A01 actually issues. Anything absent is
#: treated as VOLATILE, which is the safe direction: a short cache costs an
#: extra request, a long one costs a wrong answer.
EVM_METHOD_VOLATILITY: Final[dict[str, Volatility]] = {
    # head
    "eth_blockNumber": Volatility.HEAD,
    "eth_gasPrice": Volatility.HEAD,
    "eth_maxPriorityFeePerGas": Volatility.HEAD,
    "eth_feeHistory": Volatility.HEAD,
    # stable
    "eth_chainId": Volatility.IMMUTABLE,
    "net_version": Volatility.IMMUTABLE,
    "web3_clientVersion": Volatility.STABLE,
    "eth_getCode": Volatility.STABLE,
    # volatile unless pinned to a finalized block, which get_ttl handles
    "eth_getBalance": Volatility.VOLATILE,
    "eth_getTransactionCount": Volatility.VOLATILE,
    "eth_call": Volatility.VOLATILE,
    "eth_getStorageAt": Volatility.VOLATILE,
    # immutable once confirmed
    "eth_getTransactionReceipt": Volatility.IMMUTABLE,
    "eth_getTransactionByHash": Volatility.IMMUTABLE,
    "eth_getBlockByHash": Volatility.IMMUTABLE,
    "eth_getBlockByNumber": Volatility.VOLATILE,  # "latest" is common; see get_ttl
    "eth_getLogs": Volatility.VOLATILE,
}


# ==============================================================================
# KEYS
# ==============================================================================

def cache_key(chain: str, method: str, params: Any) -> str:
    """
    Stable key for one logical read.

    Deliberately excludes the endpoint. Two providers answering the same
    question about the same chain must return the same fact, and keying on the
    provider would multiply every entry by the endpoint count and re-spend the
    budget the cache exists to protect. It also means a result fetched before
    a failover is still valid after it.
    """
    payload = json.dumps(params, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8"), usedforsecurity=False).hexdigest()[:32]
    return f"{chain}:{method}:{digest}"


# ==============================================================================
# TTL POLICY
# ==============================================================================

#: Named block tags accepted by EVM JSON-RPC.
_NAMED_TAGS: Final[frozenset[str]] = frozenset(
    {"latest", "pending", "earliest", "safe", "finalized"}
)

#: "0x" plus at most 16 hex digits. Longer 0x strings are addresses (42) or
#: hashes (66), never block numbers.
_MAX_BLOCK_TAG_LENGTH: Final[int] = 18


def _block_tag(params: Any) -> str | None:
    """
    The block tag in an EVM parameter list, if there is one.

    Scanned from the end, because every method that takes a block tag takes it
    last: ``eth_getBalance(address, tag)``, ``eth_call(callObject, tag)``,
    ``eth_getBlockByNumber(tag, fullTx)``. Scanning forwards finds the address
    first and tries to read it as a block number.

    Only the last string argument is considered. If that one is not a block
    tag, the call has none -- continuing to scan would eventually reach the
    address and misread it.
    """
    if not isinstance(params, (list, tuple)):
        return None

    for item in reversed(params):
        if not isinstance(item, str):
            continue  # trailing bools like eth_getBlockByNumber's fullTx flag
        if item in _NAMED_TAGS:
            return item
        if item.startswith("0x") and len(item) <= _MAX_BLOCK_TAG_LENGTH:
            try:
                int(item, 16)
            except ValueError:
                return None
            return item
        return None

    return None


def resolve_volatility(
    method: str,
    params: Any = None,
    *,
    head_block: int | None = None,
    confirmations: int = 12,
) -> Volatility:
    """
    Classify one call.

    A read pinned to a block that is already buried deeper than the chain's
    confirmation depth cannot change, so it is promoted to IMMUTABLE however
    volatile the method is in general. This is what makes historical analysis
    affordable on a free tier: a backtest re-reading the same 2021 window
    pays for it once.
    """
    base = EVM_METHOD_VOLATILITY.get(method, Volatility.VOLATILE)

    if base in {Volatility.IMMUTABLE, Volatility.NEVER, Volatility.HEAD}:
        return base

    tag = _block_tag(params)
    if tag is None:
        return base

    # "pending" is never stable; the others resolve against the head.
    if tag in {"latest", "pending", "safe"}:
        return Volatility.VOLATILE
    if tag == "earliest":
        return Volatility.IMMUTABLE
    if tag == "finalized":
        return Volatility.IMMUTABLE

    if head_block is None:
        return base

    try:
        block = int(tag, 16)
    except (TypeError, ValueError):
        return base

    if head_block - block >= confirmations:
        return Volatility.IMMUTABLE
    return Volatility.VOLATILE


def ttl_for(volatility: Volatility) -> float:
    return TTL_BY_VOLATILITY[volatility]


# ==============================================================================
# CACHE
# ==============================================================================

@dataclass(slots=True)
class Entry:
    """One cached result."""

    value: Any
    expires_at: float
    volatility: Volatility
    stored_at: float
    #: Provider the value came from. Carried for provenance, not for keying:
    #: evidence has to record which provider asserted a fact.
    provider: str = ""

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at


class ResponseCache:
    """
    Bounded LRU cache over chain reads.

    Thread-safe for the same reason the rate limiter is: pipeline stages may
    run off the calling thread, and a cache that loses entries to a race just
    silently re-spends the request budget.
    """

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Clock | None = None,
        enabled: bool = True,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be > 0")

        self._entries: OrderedDict[str, Entry] = OrderedDict()
        self._max_entries = max_entries
        self._clock: Clock = clock or time.monotonic
        self._enabled = enabled
        self._lock = threading.Lock()

        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0

    # -- access ----------------------------------------------------------

    def get(self, key: str) -> tuple[bool, Any]:
        """
        Look up ``key``.

        Returns ``(found, value)`` rather than ``value | None`` because a
        cached ``None`` is a real answer -- ``eth_getTransactionReceipt``
        returns null for an unmined hash -- and collapsing it into a miss
        would re-query on every call.
        """
        if not self._enabled:
            return False, None

        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return False, None

            now = self._clock()
            if entry.is_expired(now):
                del self._entries[key]
                self.expirations += 1
                self.misses += 1
                return False, None

            self._entries.move_to_end(key)
            self.hits += 1
            return True, entry.value

    def put(
        self,
        key: str,
        value: Any,
        volatility: Volatility,
        *,
        provider: str = "",
    ) -> None:
        """Store a successful result. NEVER-class results are dropped."""
        if not self._enabled or volatility == Volatility.NEVER:
            return

        ttl = ttl_for(volatility)
        if ttl <= 0:
            return

        now = self._clock()
        with self._lock:
            self._entries[key] = Entry(
                value=value,
                expires_at=now + ttl,
                volatility=volatility,
                stored_at=now,
                provider=provider,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
                self.evictions += 1

    def provider_for(self, key: str) -> str | None:
        """
        Which provider supplied a cached value.

        Evidence provenance has to name the provider that asserted a fact, and
        a cache hit must not be attributed to whichever endpoint happened to
        be selected for the call that hit it.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.is_expired(self._clock()):
                return None
            return entry.provider

    # -- maintenance -----------------------------------------------------

    def invalidate(self, key: str) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    def invalidate_chain(self, chain: str) -> int:
        """Drop every entry for one chain, e.g. after a detected reorg."""
        prefix = f"{chain}:"
        with self._lock:
            doomed = [k for k in self._entries if k.startswith(prefix)]
            for key in doomed:
                del self._entries[key]
            return len(doomed)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def purge_expired(self) -> int:
        with self._lock:
            now = self._clock()
            doomed = [k for k, e in self._entries.items() if e.is_expired(now)]
            for key in doomed:
                del self._entries[key]
            self.expirations += len(doomed)
            return len(doomed)

    # -- reporting -------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def snapshot(self) -> dict[str, Any]:
        """Cache statistics, for doctor."""
        with self._lock:
            total = self.hits + self.misses
            by_class: dict[str, int] = {}
            now = self._clock()
            for entry in self._entries.values():
                if not entry.is_expired(now):
                    by_class[entry.volatility.value] = by_class.get(entry.volatility.value, 0) + 1
            return {
                "enabled": self._enabled,
                "entries": len(self._entries),
                "max_entries": self._max_entries,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else None,
                "evictions": self.evictions,
                "expirations": self.expirations,
                "by_volatility": by_class,
            }


__all__ = [
    "Volatility",
    "TTL_BY_VOLATILITY",
    "EVM_METHOD_VOLATILITY",
    "IMMUTABLE_TTL",
    "DEFAULT_MAX_ENTRIES",
    "Entry",
    "ResponseCache",
    "cache_key",
    "resolve_volatility",
    "ttl_for",
]
