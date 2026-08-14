"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.utils.decorators

Purpose:
    Reusable behavior decorators for the planning subsystem.

All decorators transparently support both synchronous and asynchronous
callables. They centralize retry, validation, timing, logging, caching,
checkpoint, tracing, and transaction boilerplate.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import time
from typing import Any, Callable, ParamSpec, TypeVar

from .constants import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_MAX_CACHE_ENTRIES,
    MAX_RETRY,
    RetryPolicy,
)
from .timers import BackoffConfig, ExponentialBackoff
from .validation import ValidationResult

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger("a01.planning.utils")

# ==============================================================================
# LOGGING
# ==============================================================================


def log_execution(
    logger_: logging.Logger | None = None,
    *,
    level: int = logging.INFO,
    message: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Log function entry, exit, duration, and errors.

    Works for both sync and async callables.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        log = logger_ or logger
        label = message or func.__qualname__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                started = time.perf_counter()
                log.log(level, "%s started", label)

                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    log.exception("%s failed: %s", label, exc)
                    raise

                elapsed_ms = (time.perf_counter() - started) * 1000.0
                log.log(level, "%s completed in %.2fms", label, elapsed_ms)
                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = time.perf_counter()
            log.log(level, "%s started", label)

            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                log.exception("%s failed: %s", label, exc)
                raise

            elapsed_ms = (time.perf_counter() - started) * 1000.0
            log.log(level, "%s completed in %.2fms", label, elapsed_ms)
            return result

        return sync_wrapper

    return decorator


# ==============================================================================
# TIMING
# ==============================================================================


def measure_time(
    collector: Callable[[str, float], None] | None = None,
    *,
    label: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Measure a function's duration and report it.

    Parameters
    ----------
    collector
        Callable invoked as collector(label, duration_ms).
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        name = label or func.__qualname__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                started = time.perf_counter()
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - started) * 1000.0

                if collector is not None:
                    collector(name, duration_ms)

                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = time.perf_counter()
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - started) * 1000.0

            if collector is not None:
                collector(name, duration_ms)

            return result

        return sync_wrapper

    return decorator


# ==============================================================================
# VALIDATION
# ==============================================================================


def validate(
    validator: Callable[[Any], ValidationResult],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Validate the first positional argument before calling.

    Raises
    ------
    ValueError
        When validation fails.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                target = args[0] if args else kwargs.get("value")
                _raise_on_invalid(validator(target))
                return await func(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            target = args[0] if args else kwargs.get("value")
            _raise_on_invalid(validator(target))
            return func(*args, **kwargs)

        return sync_wrapper

    return decorator


def _raise_on_invalid(result: ValidationResult) -> None:
    if not result.valid:
        raise ValueError(result.error_message)


# ==============================================================================
# RETRY
# ==============================================================================


def retry(
    *,
    max_attempts: int = MAX_RETRY,
    policy: RetryPolicy | str = RetryPolicy.EXPONENTIAL,
    base_seconds: float = 1.0,
    factor: float = 2.0,
    max_seconds: float = 60.0,
    jittered: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[int, Exception], None] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Retry a callable with backoff.

    Supports both sync and async callables.

    Raises
    ------
    ValueError
        When max_attempts is less than 1.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    policy_name = policy.value if isinstance(policy, RetryPolicy) else policy

    backoff = ExponentialBackoff(
        BackoffConfig(
            base_seconds=base_seconds,
            factor=factor,
            max_seconds=max_seconds,
        )
    )

    def decorator(func: Callable[P, R]) -> Callable[P, R]:

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                last_exc: Exception | None = None

                for attempt in range(max_attempts):
                    try:
                        return await func(*args, **kwargs)

                    except exceptions as exc:
                        last_exc = exc

                        if attempt == max_attempts - 1:
                            raise

                        if on_retry is not None:
                            on_retry(attempt + 1, exc)

                        await asyncio.sleep(
                            _policy_delay(
                                policy_name,
                                backoff,
                                attempt,
                                jittered,
                            )
                        )

                raise last_exc or RuntimeError("retry exhausted")

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exc: Exception | None = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)

                except exceptions as exc:
                    last_exc = exc

                    if attempt == max_attempts - 1:
                        raise

                    if on_retry is not None:
                        on_retry(attempt + 1, exc)

                    time.sleep(
                        _policy_delay(
                            policy_name,
                            backoff,
                            attempt,
                            jittered,
                        )
                    )

            raise last_exc or RuntimeError("retry exhausted")

        return sync_wrapper

    return decorator


def _policy_delay(
    policy: str,
    backoff: ExponentialBackoff,
    attempt: int,
    jittered: bool,
) -> float:
    if policy in {RetryPolicy.EXPONENTIAL.value, RetryPolicy.JITTERED.value}:
        return backoff.next_delay(attempt, jittered=jittered or policy == RetryPolicy.JITTERED.value)

    if policy == RetryPolicy.FIXED.value:
        return backoff.config.base_seconds

    if policy == RetryPolicy.ALWAYS.value:
        return backoff.next_delay(attempt, jittered=jittered)

    return 0.0


# ==============================================================================
# CACHE
# ==============================================================================


def cache(
    *,
    ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    max_entries: int = DEFAULT_MAX_CACHE_ENTRIES,
    key_builder: Callable[..., Any] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Cache callable results with an in-memory TTL store.

    Supports both sync and async callables.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        store: dict[Any, tuple[float, R]] = {}
        lock = asyncio.Lock()

        def build_key(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
            if key_builder is not None:
                return key_builder(*args, **kwargs)

            try:
                import hashlib

                from .serialization import canonical_json

                payload = canonical_json(
                    {"args": list(args), "kwargs": kwargs}
                )
                return hashlib.sha256(payload.encode("utf-8")).hexdigest()
            except Exception:
                return (args, tuple(sorted(kwargs.items())))

        def _cleanup_locked() -> None:
            now = time.monotonic()
            stale = [
                key
                for key, (stored_at, _) in store.items()
                if now - stored_at >= ttl_seconds
            ]
            for key in stale:
                store.pop(key, None)

            if len(store) > max_entries:
                oldest = sorted(
                    store.items(),
                    key=lambda item: item[1][0],
                )
                for key, _ in oldest[: len(store) - max_entries]:
                    store.pop(key, None)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                key = build_key(args, kwargs)

                async with lock:
                    hit = store.get(key)

                    if hit is not None:
                        stored_at, value = hit
                        if time.monotonic() - stored_at < ttl_seconds:
                            return value

                    result = await func(*args, **kwargs)

                    store[key] = (time.monotonic(), result)
                    _cleanup_locked()
                    return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            key = build_key(args, kwargs)

            hit = store.get(key)

            if hit is not None:
                stored_at, value = hit
                if time.monotonic() - stored_at < ttl_seconds:
                    return value

            result = func(*args, **kwargs)
            store[key] = (time.monotonic(), result)
            _cleanup_locked()
            return result

        return sync_wrapper

    return decorator


# ==============================================================================
# TRACE
# ==============================================================================


def trace(
    tracer: Callable[[str, dict[str, Any]], None] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Emit a trace event around a callable.

    The tracer is invoked as tracer(phase, payload) where phase is
    one of "start" or "end".
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                if tracer is not None:
                    tracer("start", {"name": func.__qualname__})

                result = await func(*args, **kwargs)

                if tracer is not None:
                    tracer("end", {"name": func.__qualname__})

                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if tracer is not None:
                tracer("start", {"name": func.__qualname__})

            result = func(*args, **kwargs)

            if tracer is not None:
                tracer("end", {"name": func.__qualname__})

            return result

        return sync_wrapper

    return decorator


# ==============================================================================
# TRANSACTION
# ==============================================================================


def transaction(
    commit: Callable[[], None] | None = None,
    rollback: Callable[[], None] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Wrap a callable in a transaction.

    On success ``commit`` runs; on exception ``rollback`` runs and the
    exception is re-raised.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    if rollback is not None:
                        rollback()
                    raise

                if commit is not None:
                    commit()

                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                result = func(*args, **kwargs)
            except Exception:
                if rollback is not None:
                    rollback()
                raise

            if commit is not None:
                commit()

            return result

        return sync_wrapper

    return decorator


# ==============================================================================
# CHECKPOINT
# ==============================================================================


def checkpoint(
    saver: Callable[[str, Any], None],
    *,
    label: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Persist the callable's result via a checkpoint saver.

    The saver is invoked as saver(checkpoint_id, result).
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        checkpoint_id = label or func.__qualname__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                result = await func(*args, **kwargs)
                saver(checkpoint_id, result)
                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            result = func(*args, **kwargs)
            saver(checkpoint_id, result)
            return result

        return sync_wrapper

    return decorator


# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "log_execution",
    "measure_time",
    "validate",
    "retry",
    "cache",
    "trace",
    "transaction",
    "checkpoint",
]
