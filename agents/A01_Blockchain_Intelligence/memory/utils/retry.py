"""
Memory Retry Utilities

Async retry with configurable backoff for flaky backends.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")

Retryable = Callable[..., Awaitable[T]]


class RetryError(Exception):
    pass


async def retry(
    fn: Retryable[T],
    *args: Any,
    attempts: int = 3,
    base_delay: float = 0.05,
    max_delay: float = 1.0,
    backoff: float = 2.0,
    jitter: bool = True,
    **kwargs: Any,
) -> T:
    """
    Await fn(*args, **kwargs), retrying on exceptions with backoff.
    """
    if attempts < 1:
        raise RetryError("attempts must be >= 1.")
    last_error: Exception | None = None
    delay = base_delay
    for attempt in range(1, attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == attempts:
                break
            wait = min(delay, max_delay)
            if jitter:
                wait = wait * (0.5 + (hash((attempt, wait)) % 100) / 100.0)
            await asyncio.sleep(wait)
            delay = min(delay * backoff, max_delay)
    raise RetryError(
        f"retry failed after {attempts} attempts: {last_error}"
    ) from last_error


async def retry_async(
    coro_factory: Retryable[T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """
    Alias for retry with a coroutine factory.
    """
    return await retry(coro_factory, *args, **kwargs)
