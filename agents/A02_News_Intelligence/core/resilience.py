"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.resilience

Purpose:
    Production hardening — rate limiting, circuit breakers, retries, timeouts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.A02_News_Intelligence.config.settings import Settings

logger = logging.getLogger(__name__)


# ==============================================================================
# RATE LIMITER
# ==============================================================================


class TokenBucketRateLimiter:
    """Token bucket rate limiter for API calls."""
    
    def __init__(self, rate: float, burst: int):
        """
        Args:
            rate: tokens per second
            burst: maximum bucket size
        """
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> None:
        """Wait until tokens are available."""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
                self.last_update = now
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                
                # Calculate wait time
                wait_time = (tokens - self.tokens) / self.rate
                await asyncio.sleep(min(wait_time, 1.0))  # Cap sleep to 1s
    
    def try_acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens without blocking."""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_update = now
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class SlidingWindowRateLimiter:
    """Sliding window rate limiter for request counting."""
    
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: list[float] = []
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        async with self._lock:
            while True:
                now = time.monotonic()
                # Remove old requests outside window
                cutoff = now - self.window_seconds
                self.requests = [t for t in self.requests if t > cutoff]
                
                if len(self.requests) < self.max_requests:
                    self.requests.append(now)
                    return
                
                # Wait until oldest request expires
                wait_time = self.requests[0] + self.window_seconds - now
                await asyncio.sleep(max(wait_time, 0.1))


# ==============================================================================
# CIRCUIT BREAKER
# ==============================================================================


class CircuitState:
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Circuit breaker for external service calls."""
    
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 30.0
    
    _state: str = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    
    @property
    def state(self) -> str:
        if self._state == CircuitState.OPEN:
            # Check if timeout has passed
            if time.monotonic() - self._last_failure_time >= self.timeout_seconds:
                return CircuitState.HALF_OPEN
        return self._state
    
    async def call(self, func, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpenError("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise
    
    async def _on_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
            logger.debug("Circuit breaker: success, state=%s", self._state)
    
    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._success_count = 0
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
            
            logger.warning("Circuit breaker: failure %d/%d, state=%s", 
                          self._failure_count, self.failure_threshold, self._state)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


# ==============================================================================
# RETRY POLICY
# ==============================================================================


@dataclass
class RetryPolicy:
    """Configurable retry policy with exponential backoff."""
    
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (Exception,)
    
    async def execute(self, func, *args, **kwargs) -> Any:
        """Execute function with retry logic."""
        last_exception = None
        
        for attempt in range(self.max_attempts):
            try:
                return await func(*args, **kwargs)
            except self.retryable_exceptions as e:
                last_exception = e
                if attempt == self.max_attempts - 1:
                    break
                
                delay = min(
                    self.base_delay * (self.exponential_base ** attempt),
                    self.max_delay
                )
                if self.jitter:
                    import random
                    delay *= (0.5 + random.random())  # 50-150% of delay
                
                logger.warning("Retry %d/%d after %.1fs: %s", 
                              attempt + 1, self.max_attempts, delay, e)
                await asyncio.sleep(delay)
        
        raise last_exception


# ==============================================================================
# TIMEOUT MANAGER
# ==============================================================================


class TimeoutManager:
    """Manages timeouts for async operations with cascading timeouts."""
    
    def __init__(self, default_timeout: float = 30.0):
        self.default_timeout = default_timeout
        self._timeouts: dict[str, float] = {}
    
    def set_timeout(self, operation: str, timeout: float) -> None:
        self._timeouts[operation] = timeout
    
    def get_timeout(self, operation: str) -> float:
        return self._timeouts.get(operation, self.default_timeout)
    
    async def run_with_timeout(self, operation: str, coro) -> Any:
        """Run coroutine with operation-specific timeout."""
        timeout = self.get_timeout(operation)
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Operation %s timed out after %.1fs", operation, timeout)
            raise


# ==============================================================================
# RESILIENCE MANAGER (combines all)
# ==============================================================================


class ResilienceManager:
    """Central manager for all resilience patterns."""
    
    def __init__(self, settings: "Settings | None" = None):
        self.settings = settings
        
        # Rate limiters per service
        self._rate_limiters: dict[str, TokenBucketRateLimiter] = {}
        self._window_limiters: dict[str, SlidingWindowRateLimiter] = {}
        
        # Circuit breakers per service
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        
        # Timeout manager
        self.timeout_manager = TimeoutManager()
        
        # Default retry policy
        self.retry_policy = RetryPolicy()
        
        # Initialize from settings if provided
        if settings:
            self._init_from_settings(settings)
    
    def _init_from_settings(self, settings: "Settings") -> None:
        """Initialize rate limiters from settings."""
        # Binance
        self._rate_limiters["binance"] = TokenBucketRateLimiter(
            rate=settings.market.binance_rate_limit or 10.0,
            burst=settings.market.binance_burst_limit or 20
        )
        
        # Alpha Vantage
        if settings.market.alpha_vantage_api_key.get_secret_value():
            self._rate_limiters["alpha_vantage"] = TokenBucketRateLimiter(
                rate=5.0,  # 5 requests/second (free tier)
                burst=5
            )
        
        # News APIs
        if settings.news.tiingo_api_key.get_secret_value():
            self._rate_limiters["tiingo"] = TokenBucketRateLimiter(
                rate=10.0, burst=20
            )
        
        if settings.news.newsapi_key.get_secret_value():
            self._rate_limiters["newsapi"] = TokenBucketRateLimiter(
                rate=1.0,  # Very conservative
                burst=2
            )
        
        # Circuit breakers
        for service in ["binance", "alpha_vantage", "tiingo", "newsapi", "telegram", "x", "reddit"]:
            self._circuit_breakers[service] = CircuitBreaker(
                failure_threshold=5,
                success_threshold=2,
                timeout_seconds=60.0
            )
        
        # Timeouts
        self.timeout_manager.set_timeout("binance_klines", 15.0)
        self.timeout_manager.set_timeout("alpha_vantage", 30.0)
        self.timeout_manager.set_timeout("news_fetch", 30.0)
        self.timeout_manager.set_timeout("social_fetch", 20.0)
    
    def get_rate_limiter(self, service: str) -> TokenBucketRateLimiter | None:
        return self._rate_limiters.get(service)
    
    def get_circuit_breaker(self, service: str) -> CircuitBreaker | None:
        return self._circuit_breakers.get(service)
    
    async def call_with_resilience(
        self, 
        service: str, 
        func, 
        *args, 
        **kwargs
    ) -> Any:
        """Call function with full resilience (rate limit + circuit breaker + retry + timeout)."""
        
        # Rate limiting
        limiter = self._rate_limiters.get(service)
        if limiter:
            await limiter.acquire()
        
        # Circuit breaker
        breaker = self._circuit_breakers.get(service)
        if breaker:
            return await breaker.call(
                self.retry_policy.execute,
                self.timeout_manager.run_with_timeout,
                service, func, *args, **kwargs
            )
        
        # No circuit breaker, just retry + timeout
        return await self.retry_policy.execute(
            self.timeout_manager.run_with_timeout,
            service, func, *args, **kwargs
        )


# ==============================================================================
# GLOBAL INSTANCE
# ==============================================================================

_resilience_manager: ResilienceManager | None = None


def get_resilience_manager(settings: "Settings | None" = None) -> ResilienceManager:
    global _resilience_manager
    if _resilience_manager is None:
        _resilience_manager = ResilienceManager(settings)
    elif settings and _resilience_manager.settings is None:
        _resilience_manager._init_from_settings(settings)
    return _resilience_manager


__all__ = [
    "TokenBucketRateLimiter",
    "SlidingWindowRateLimiter",
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerOpenError",
    "RetryPolicy",
    "TimeoutManager",
    "ResilienceManager",
    "get_resilience_manager",
]