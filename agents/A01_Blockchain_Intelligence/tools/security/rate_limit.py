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
from typing import Dict, List, Mapping, Optional, Union

__all__ = ["RateLimiter", "RateLimitError", "RateLimitPolicy"]


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

    def __init__(self, *, default_policy: Optional[RateLimitPolicy] = None) -> None:
        self._lock = threading.RLock()
        self._windows: Dict[str, List[float]] = {}
        self._policies: Dict[str, RateLimitPolicy] = {}
        self._default_policy = default_policy

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
        """Consume one token; raises :class:`RateLimitError` when exhausted."""
        p = self._resolve(name, policy)
        now = time.monotonic()
        slots = self._prune(name, p.window, now)
        if len(slots) >= p.limit:
            retry_after = p.window - (now - slots[0]) if slots else 0.0
            raise RateLimitError(
                name,
                limit=p.limit,
                window=p.window,
                retry_after=retry_after,
                scope=p.scope,
            )
        with self._lock:
            self._windows[name].append(now)
        return True

    def can(self, name: str, *, policy: Optional[RateLimitPolicy] = None) -> bool:
        """Non-consuming check: would an :meth:`allow` currently succeed?"""
        p = self._resolve(name, policy)
        slots = self._prune(name, p.window, time.monotonic())
        return len(slots) < p.limit

    def remaining(self, name: str, *, policy: Optional[RateLimitPolicy] = None) -> int:
        """Tokens left in the current window for ``name``."""
        p = self._resolve(name, policy)
        slots = self._prune(name, p.window, time.monotonic())
        return max(0, p.limit - len(slots))

    def reset(self, name: Optional[str] = None) -> None:
        with self._lock:
            if name is None:
                self._windows.clear()
            else:
                self._windows.pop(name, None)

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

    def _prune(self, name: str, window: float, now: float) -> List[float]:
        """Return (and store) the list of timestamps inside the window."""
        with self._lock:
            slots = self._windows.setdefault(name, [])
            kept = [t for t in slots if t > now - window]
            self._windows[name] = kept
            return kept