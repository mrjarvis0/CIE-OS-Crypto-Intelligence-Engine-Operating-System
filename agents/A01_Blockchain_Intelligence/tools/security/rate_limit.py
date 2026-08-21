"""
Tools :: Security :: Rate Limit
===============================

Sliding-window rate limiting for tool invocations and external service calls.

Throttling protects both the platform and the providers touched by adapters:
the router/executor consult a :class:`RateLimiter` before dispatching an
expensive request. The implementation is thread-safe, stdlib-only, and uses a
fixed sliding window over :mod:`time` events.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

__all__ = ["RateLimiter", "RateLimitError", "RateLimitPolicy", "DEFAULT_MAX_KEYS"]

#: Ceiling on distinct names a limiter will track before it evicts.
#: ``None`` disables eviction, which is only safe when the caller controls
#: the full set of names.
DEFAULT_MAX_KEYS = 10_000


class RateLimitError(Exception):
    """Raised when a call would exceed its registered policy window."""

    code = "RATE_LIMITED"

    def __init__(
        self,
        key: str,
        *,
        limit: int,
        window: float,
        retry_after: float,
        scope: str = "",
    ) -> None:
        self.key = key
        self.limit = limit
        self.window = window
        self.retry_after = retry_after
        self.scope = scope
        super().__init__(
            f"rate limit exceeded for {scope + ':' if scope else ''}{key} "
            f"({limit}/{window}s); retry after {retry_after:.2f}s"
        )


class RateLimitPolicy:
    """Bound for a rate-limit scope: ``limit`` requests per ``window`` seconds."""

    __slots__ = ("limit", "window", "scope")

    def __init__(self, limit: int, window: float, *, scope: str = "") -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window <= 0:
            raise ValueError("window must be > 0")
        self.limit = limit
        self.window = window
        self.scope = scope


class RateLimiter:
    """
    Thread-safe sliding window limiter.

    Policies are registered by *name* (typically a scope like ``"rpc"`` or a
    target like ``"blockchain.eth_call"``), then consumed via
    ``allow(name)``. An optional default policy applies when a name has no
    dedicated entry.
    """

    def __init__(
        self,
        *,
        default_policy: Optional[RateLimitPolicy] = None,
        max_keys: Optional[int] = DEFAULT_MAX_KEYS,
    ) -> None:
        self._lock = threading.RLock()
        self._windows: Dict[str, List[float]] = {}
        self._policies: Dict[str, RateLimitPolicy] = {}
        self._default_policy = default_policy
        self._max_keys = max_keys

    def register(self, policy: RateLimitPolicy, *, name: Optional[str] = None) -> None:
        """Register ``policy``; when ``name`` is omitted the policy ``scope`` is used."""
        key = name or policy.scope
        if not key:
            raise ValueError("a policy requires a scope or explicit name")
        with self._lock:
            self._policies[key] = policy

    def set_default(self, policy: RateLimitPolicy) -> None:
        self._default_policy = policy

    # -- core ops ---------------------------------------------------------- #

    def allow(self, name: str, *, policy: Optional[RateLimitPolicy] = None) -> bool:
        """
        Consume one token; raises :class:`RateLimitError` when exhausted.

        The check and the append happen under a **single** lock acquisition.
        They used to be two: ``_prune`` took the lock, released it, the caller
        compared the length, then re-took the lock to append. Two threads that
        interleaved in that gap both saw ``len(slots) < limit`` and both
        appended, so a limiter documented as thread-safe admitted more calls
        than its policy allowed -- exactly under the load that makes a limiter
        matter.
        """
        p = self._resolve(name, policy)
        now = time.monotonic()

        with self._lock:
            slots = self._prune_locked(name, p.window, now)
            if len(slots) >= p.limit:
                retry_after = p.window - (now - slots[0]) if slots else 0.0
                raise RateLimitError(
                    name,
                    limit=p.limit,
                    window=p.window,
                    retry_after=max(0.0, retry_after),
                    scope=p.scope,
                )
            slots.append(now)
            return True

    def can(self, name: str, *, policy: Optional[RateLimitPolicy] = None) -> bool:
        """Non-consuming check: would an :meth:`allow` currently succeed?"""
        p = self._resolve(name, policy)
        with self._lock:
            return len(self._prune_locked(name, p.window, time.monotonic())) < p.limit

    def remaining(self, name: str, *, policy: Optional[RateLimitPolicy] = None) -> int:
        """Tokens left in the current window for ``name``."""
        p = self._resolve(name, policy)
        with self._lock:
            used = len(self._prune_locked(name, p.window, time.monotonic()))
        return max(0, p.limit - used)

    def reset(self, name: Optional[str] = None) -> None:
        with self._lock:
            if name is None:
                self._windows.clear()
            else:
                self._windows.pop(name, None)

    def tracked_keys(self) -> int:
        """How many distinct names currently hold a window. Useful in tests."""
        with self._lock:
            return len(self._windows)

    # -- internals --------------------------------------------------------- #

    def _resolve(self, name: str, policy: Optional[RateLimitPolicy]) -> RateLimitPolicy:
        if policy is not None:
            return policy
        with self._lock:
            registered = self._policies.get(name)
        if registered is not None:
            return registered
        if self._default_policy is not None:
            return self._default_policy
        raise ValueError(f"no rate limit policy registered for {name!r}")

    def _prune_locked(self, name: str, window: float, now: float) -> List[float]:
        """
        Drop expired timestamps for ``name`` and return the live list.

        Caller must already hold ``self._lock``; the returned list is the
        stored one, so an append by the caller is the stored state.
        """
        slots = self._windows.get(name)
        if slots is None:
            self._evict_if_needed()
            slots = self._windows[name] = []
            return slots

        cutoff = now - window
        if slots and slots[0] <= cutoff:
            slots[:] = [t for t in slots if t > cutoff]
        return slots

    def _evict_if_needed(self) -> None:
        """
        Bound the number of tracked names.

        ``_windows`` grew one entry per distinct name, forever. Names come
        from tool identifiers and scope strings, which are caller-supplied, so
        an unbounded map is a memory-exhaustion path reachable by whoever
        chooses the names. Empty windows go first -- they carry no state worth
        keeping -- then the oldest entries by their newest timestamp.
        """
        if self._max_keys is None or len(self._windows) < self._max_keys:
            return

        empty = [k for k, v in self._windows.items() if not v]
        for key in empty:
            del self._windows[key]

        if len(self._windows) < self._max_keys:
            return

        by_age = sorted(self._windows.items(), key=lambda kv: kv[1][-1])
        for key, _ in by_age[: max(1, len(by_age) // 4)]:
            del self._windows[key]
