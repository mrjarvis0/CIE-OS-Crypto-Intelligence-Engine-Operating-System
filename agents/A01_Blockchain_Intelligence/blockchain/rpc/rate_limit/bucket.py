"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    blockchain.transport.ratelimit

Purpose:
    Keep A01 inside the request budget of the free provider tiers it runs on.

Design goals:
    - Per-provider budgets, not one global limit
    - Monotonic clock, injectable so tests need no sleeping
    - Observed 429s override the documented limit
    - No network I/O

Notes:
    Rate limiting is not politeness here, it is a correctness requirement. The
    documented free-tier ceilings A01 runs against are low -- CoinGecko's open
    tier is roughly 10/min and BlockCypher's tokenless tier is about 3/min --
    and an investigation that fans out across several detectors will exceed
    them in a second or two. What comes back is a 429, which the fallback
    manager reads as an unhealthy endpoint and takes out of rotation. Without
    a limiter, A01 disables its own providers under load and then reports
    thin evidence as if the chain had nothing to say.

    The bucket is deliberately pessimistic on penalty and slow to forgive: a
    provider that has already answered 429 is telling us its own documented
    figure was wrong for this key, this minute.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Final

#: Free tiers publish per-minute ceilings, so that is the bucket window.
WINDOW_SECONDS: Final[float] = 60.0

#: How long a provider stays throttled after answering 429. Longer than the
#: window, because the provider is reporting a budget we cannot see.
DEFAULT_PENALTY_SECONDS: Final[float] = 90.0

#: Fraction of the documented ceiling actually used. Published limits are
#: usually enforced with burst detection A01 cannot observe, so spending the
#: whole budget invites the 429 the limiter exists to avoid.
DEFAULT_SAFETY_FACTOR: Final[float] = 0.8


Clock = Callable[[], float]


@dataclass(slots=True)
class BucketState:
    """Token bucket for one provider."""

    capacity: float
    tokens: float
    refill_per_second: float
    last_refill: float

    #: Monotonic deadline before which no request may go out, set by a 429.
    penalty_until: float = 0.0
    #: Lifetime counters, for doctor and for backtest reproducibility notes.
    granted: int = 0
    denied: int = 0
    throttle_events: int = 0

    def _refill(self, now: float) -> None:
        elapsed = now - self.last_refill
        if elapsed <= 0:
            return
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.last_refill = now

    def is_penalised(self, now: float) -> bool:
        return now < self.penalty_until

    def wait_time(self, now: float, tokens: float = 1.0) -> float:
        """Seconds until ``tokens`` are available. 0.0 when ready now."""
        if self.is_penalised(now):
            return self.penalty_until - now

        self._refill(now)
        if self.tokens >= tokens:
            return 0.0
        if self.refill_per_second <= 0:
            return float("inf")
        return (tokens - self.tokens) / self.refill_per_second


class RateLimiter:
    """
    Per-provider token buckets.

    Thread-safe: A01's pipeline stages run under a timeout wrapper that may
    execute them off the calling thread, and two detectors querying the same
    provider must share one budget rather than each getting a private copy.
    """

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        safety_factor: float = DEFAULT_SAFETY_FACTOR,
        penalty_seconds: float = DEFAULT_PENALTY_SECONDS,
    ) -> None:
        if not 0 < safety_factor <= 1:
            raise ValueError("safety_factor must be in (0, 1]")
        if penalty_seconds <= 0:
            raise ValueError("penalty_seconds must be > 0")

        self._clock: Clock = clock or time.monotonic
        self._safety_factor = safety_factor
        self._penalty_seconds = penalty_seconds
        self._buckets: dict[str, BucketState] = {}
        self._lock = threading.Lock()

    # -- registration ----------------------------------------------------

    def register(self, provider: str, rate_limit_per_minute: int) -> None:
        """
        Declare a provider's budget.

        Re-registering with the same limit is a no-op rather than a reset, so
        rebuilding a dispatcher does not hand a throttled provider a fresh
        allowance it has not earned.
        """
        if rate_limit_per_minute <= 0:
            raise ValueError(f"{provider}: rate_limit_per_minute must be > 0")

        capacity = max(1.0, rate_limit_per_minute * self._safety_factor)
        with self._lock:
            existing = self._buckets.get(provider)
            if existing is not None and existing.capacity == capacity:
                return
            now = self._clock()
            self._buckets[provider] = BucketState(
                capacity=capacity,
                tokens=capacity,
                refill_per_second=capacity / WINDOW_SECONDS,
                last_refill=now,
            )

    # -- consumption -----------------------------------------------------

    def try_acquire(self, provider: str, tokens: float = 1.0) -> bool:
        """
        Take ``tokens`` if the budget allows. Never blocks.

        An unregistered provider is allowed through: the limiter's job is to
        protect known budgets, not to gate calls it was never told about.
        """
        with self._lock:
            bucket = self._buckets.get(provider)
            if bucket is None:
                return True

            now = self._clock()
            if bucket.is_penalised(now):
                bucket.denied += 1
                return False

            bucket._refill(now)
            if bucket.tokens < tokens:
                bucket.denied += 1
                return False

            bucket.tokens -= tokens
            bucket.granted += 1
            return True

    def wait_time(self, provider: str, tokens: float = 1.0) -> float:
        """Seconds until ``provider`` can serve a request."""
        with self._lock:
            bucket = self._buckets.get(provider)
            if bucket is None:
                return 0.0
            return bucket.wait_time(self._clock(), tokens)

    # -- feedback --------------------------------------------------------

    def penalise(self, provider: str, retry_after_seconds: float | None = None) -> None:
        """
        Record that ``provider`` answered 429.

        ``retry_after_seconds`` comes from the response header when present.
        The provider's own figure is trusted over the default, but only
        upward: a Retry-After of 1 second after a 429 is not a reason to
        resume immediately.
        """
        with self._lock:
            bucket = self._buckets.get(provider)
            if bucket is None:
                return

            now = self._clock()
            penalty = self._penalty_seconds
            if retry_after_seconds is not None and retry_after_seconds > penalty:
                penalty = retry_after_seconds

            bucket.penalty_until = max(bucket.penalty_until, now + penalty)
            bucket.tokens = 0.0
            bucket.last_refill = now
            bucket.throttle_events += 1

    def reset(self, provider: str) -> None:
        """Clear a provider's penalty and refill it. For tests and doctor."""
        with self._lock:
            bucket = self._buckets.get(provider)
            if bucket is None:
                return
            bucket.penalty_until = 0.0
            bucket.tokens = bucket.capacity
            bucket.last_refill = self._clock()

    # -- reporting -------------------------------------------------------

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Per-provider budget state, for doctor."""
        with self._lock:
            now = self._clock()
            report: dict[str, dict[str, Any]] = {}
            for provider, bucket in self._buckets.items():
                bucket._refill(now)
                report[provider] = {
                    "capacity": round(bucket.capacity, 2),
                    "tokens": round(bucket.tokens, 2),
                    "per_minute": round(bucket.refill_per_second * WINDOW_SECONDS, 2),
                    "throttled": bucket.is_penalised(now),
                    "throttled_for": round(max(0.0, bucket.penalty_until - now), 1),
                    "granted": bucket.granted,
                    "denied": bucket.denied,
                    "throttle_events": bucket.throttle_events,
                }
            return report

    def throttled_providers(self) -> tuple[str, ...]:
        with self._lock:
            now = self._clock()
            return tuple(
                provider
                for provider, bucket in self._buckets.items()
                if bucket.is_penalised(now)
            )


__all__ = [
    "WINDOW_SECONDS",
    "DEFAULT_PENALTY_SECONDS",
    "DEFAULT_SAFETY_FACTOR",
    "BucketState",
    "RateLimiter",
]
