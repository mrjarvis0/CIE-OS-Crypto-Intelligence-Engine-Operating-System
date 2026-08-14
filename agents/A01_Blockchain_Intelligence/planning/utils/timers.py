"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    planning.utils.timers

Purpose:
    Timing, deadline, timeout, backoff, and budget infrastructure for
    the planning subsystem.

Used to measure planning/execution durations, enforce deadlines,
compute retry delays, and track execution budgets.
"""

from __future__ import annotations

import asyncio
import random
import time

from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Iterator

from .constants import (
    DEFAULT_BACKOFF_BASE_SECONDS,
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_BACKOFF_MAX_SECONDS,
    DEFAULT_JITTER_RATIO,
)

# ==============================================================================
# STOPWATCH
# ==============================================================================


class Stopwatch:
    """
    Lightweight elapsed-time tracker.

    Examples
    --------
        stopwatch = Stopwatch()

        await some_work()

        elapsed_ms = stopwatch.elapsed_ms()
    """

    def __init__(self) -> None:
        self._started: float = time.perf_counter()
        self._accumulated: float = 0.0
        self._running: bool = True

    def start(self) -> None:
        """Resume timing if stopped."""
        if self._running:
            return
        self._started = time.perf_counter()
        self._running = True

    def stop(self) -> float:
        """Pause timing and return elapsed seconds so far."""
        if not self._running:
            return self._accumulated
        self._accumulated += time.perf_counter() - self._started
        self._running = False
        return self._accumulated

    def restart(self) -> float:
        """Reset and return the prior elapsed time."""
        previous = self.elapsed_seconds()
        self._started = time.perf_counter()
        self._accumulated = 0.0
        self._running = True
        return previous

    def elapsed_seconds(self) -> float:
        """Return elapsed time in seconds."""
        if not self._running:
            return self._accumulated
        return self._accumulated + (time.perf_counter() - self._started)

    def elapsed_ms(self) -> float:
        """Return elapsed time in milliseconds."""
        return self.elapsed_seconds() * 1000.0

    @property
    def is_running(self) -> bool:
        """Whether the stopwatch is currently timing."""
        return self._running


# ==============================================================================
# TIMER CONTEXT MANAGERS
# ==============================================================================

_TimeCallback = Callable[[str, float], None]


@contextmanager
def timer(
    name: str = "operation",
    *,
    callback: _TimeCallback | None = None,
) -> Iterator[Stopwatch]:
    """
    Measure a synchronous block with a context manager.

    Yields a running :class:`Stopwatch`; its total elapsed milliseconds are
    reported to the optional callback on exit.

    Examples
    --------
        with timer("plan", callback=logger):
            build_plan()
    """

    stopwatch = Stopwatch()

    try:
        yield stopwatch
    finally:
        elapsed_ms = stopwatch.elapsed_ms()

        if callback is not None:
            callback(name, elapsed_ms)


@asynccontextmanager
async def async_timer(
    name: str = "operation",
    *,
    callback: _TimeCallback | None = None,
) -> AsyncIterator[Stopwatch]:
    """
    Measure an asynchronous block with a context manager.

    Works like :func:`timer` for async code paths.

    Examples
    --------
        async with async_timer("execute", callback=logger):
            await execute_plan()
    """

    stopwatch = Stopwatch()

    try:
        yield stopwatch
    finally:
        elapsed_ms = stopwatch.elapsed_ms()

        if callback is not None:
            callback(name, elapsed_ms)


# ==============================================================================
# DEADLINE
# ==============================================================================


class Deadline:
    """
    Tracks whether a deadline has passed.

    Examples
    --------
        deadline = Deadline(timeout_seconds=30)

        if deadline.expired:
            raise TimeoutError("deadline exceeded")
    """

    def __init__(
        self,
        timeout_seconds: float,
        *,
        started_at: float | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self.timeout_seconds = timeout_seconds
        self._started_at = started_at if started_at is not None else time.monotonic()

    @property
    def started_at(self) -> float:
        """Monotonic start time."""
        return self._started_at

    @property
    def remaining_seconds(self) -> float:
        """Seconds remaining before the deadline expires."""
        return max(0.0, self._started_at + self.timeout_seconds - time.monotonic())

    @property
    def expired(self) -> bool:
        """Whether the deadline has passed."""
        return self.remaining_seconds <= 0.0

    @property
    def elapsed_seconds(self) -> float:
        """Seconds elapsed since the deadline was created."""
        return time.monotonic() - self._started_at

    def extend(self, seconds: float) -> None:
        """Extend the deadline by additional seconds."""
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        self.timeout_seconds += seconds


# ==============================================================================
# TIMEOUT HELPERS
# ==============================================================================


def check_timeout(
    deadline: Deadline,
    *,
    message: str = "operation timed out",
) -> None:
    """Raise TimeoutError when the deadline has expired."""
    if deadline.expired:
        raise TimeoutError(message)


async def with_timeout(
    coroutine: Any,
    timeout_seconds: float,
    *,
    message: str = "operation timed out",
) -> Any:
    """
    Await a coroutine under a timeout.

    Raises
    ------
    TimeoutError
        When the coroutine does not complete in time.
    """

    return await asyncio.wait_for(
        coroutine,
        timeout=timeout_seconds,
    )


# ==============================================================================
# RETRY DELAY / BACKOFF
# ==============================================================================


@dataclass(slots=True)
class BackoffConfig:
    """
    Exponential backoff configuration.
    """

    base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS

    factor: float = DEFAULT_BACKOFF_FACTOR

    max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS

    jitter_ratio: float = DEFAULT_JITTER_RATIO

    def __post_init__(self) -> None:
        if self.base_seconds <= 0:
            raise ValueError("base_seconds must be positive")

        if self.factor < 1.0:
            raise ValueError("factor must be >= 1.0")

        if not 0.0 <= self.jitter_ratio <= 1.0:
            raise ValueError("jitter_ratio must be between 0 and 1")


class ExponentialBackoff:
    """
    Computes retry delays with optional jitter.

    Examples
    --------
        backoff = ExponentialBackoff()

        delay = backoff.next_delay(attempt=2)
    """

    def __init__(
        self,
        config: BackoffConfig | None = None,
    ) -> None:
        self.config = config or BackoffConfig()

    def delay_for(self, attempt: int) -> float:
        """Return the delay for a given zero-based attempt index."""
        if attempt < 0:
            raise ValueError("attempt must be >= 0")

        delay = self.config.base_seconds * (self.config.factor**attempt)

        return min(delay, self.config.max_seconds)

    def delay_for_jittered(self, attempt: int) -> float:
        """Return a jittered delay for a given attempt index."""
        delay = self.delay_for(attempt)

        if self.config.jitter_ratio <= 0.0:
            return delay

        jitter_range = delay * self.config.jitter_ratio
        return delay + random.uniform(-jitter_range, jitter_range)

    def next_delay(
        self,
        attempt: int,
        *,
        jittered: bool = True,
    ) -> float:
        """Return the next sleep delay for the given attempt."""
        if jittered:
            return self.delay_for_jittered(attempt)

        return self.delay_for(attempt)


def retry_delay(
    attempt: int,
    *,
    base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    factor: float = DEFAULT_BACKOFF_FACTOR,
    max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
    jittered: bool = True,
) -> float:
    """
    Compute a retry delay.

    Parameters
    ----------
    attempt
        Zero-based attempt index.

    base_seconds
        Initial delay.

    factor
        Exponential growth factor.

    max_seconds
        Maximum allowed delay.

    jittered
        When True, add +/- jitter to avoid thundering herds.
    """

    backoff = ExponentialBackoff(
        BackoffConfig(
            base_seconds=base_seconds,
            factor=factor,
            max_seconds=max_seconds,
        )
    )

    return backoff.next_delay(attempt, jittered=jittered)


async def sleep_retry(
    attempt: int,
    *,
    base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
    factor: float = DEFAULT_BACKOFF_FACTOR,
    max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
    jittered: bool = True,
) -> None:
    """Sleep for the computed retry delay."""
    delay = retry_delay(
        attempt,
        base_seconds=base_seconds,
        factor=factor,
        max_seconds=max_seconds,
        jittered=jittered,
    )
    await asyncio.sleep(delay)


# ==============================================================================
# SCHEDULER CLOCK
# ==============================================================================


class SchedulerClock:
    """
    Provides a stable logical clock for the scheduler.

    Supports monotonic time and optional simulated time for tests.
    """

    def __init__(self, *, simulate: bool = False) -> None:
        self._simulate = simulate
        self._simulated_time: float = 0.0

    def now(self) -> float:
        """Return the current clock time in seconds."""
        if self._simulate:
            return self._simulated_time
        return time.monotonic()

    def advance(self, seconds: float) -> None:
        """Advance the simulated clock (no-op without simulation)."""
        if self._simulate:
            self._simulated_time += seconds

    def reset(self) -> None:
        """Reset the simulated clock."""
        self._simulated_time = 0.0


# ==============================================================================
# EXECUTION BUDGET
# ==============================================================================


@dataclass(slots=True)
class BudgetLimits:
    """
    Hard limits for an execution budget.
    """

    max_seconds: float | None = None

    max_steps: int | None = None

    max_tool_calls: int | None = None


class ExecutionBudget:
    """
    Tracks resource consumption against hard limits.

    When any limit is exceeded the budget is exhausted and the
    execution should halt and escalate.
    """

    def __init__(
        self,
        limits: BudgetLimits | None = None,
    ) -> None:
        self.limits = limits or BudgetLimits()
        self._started_at: float | None = None
        self._steps = 0
        self._tool_calls = 0

    def start(self) -> None:
        """Start the budget clock."""
        if self._started_at is None:
            self._started_at = time.monotonic()

    def record_step(self) -> None:
        """Record one step of execution."""
        self._steps += 1

    def record_tool_call(self) -> None:
        """Record one tool invocation."""
        self._tool_calls += 1

    @property
    def elapsed_seconds(self) -> float:
        """Seconds elapsed since the budget started."""
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    @property
    def steps(self) -> int:
        """Number of recorded steps."""
        return self._steps

    @property
    def tool_calls(self) -> int:
        """Number of recorded tool calls."""
        return self._tool_calls

    @property
    def time_exceeded(self) -> bool:
        """Whether the time limit has been exceeded."""
        if self.limits.max_seconds is None:
            return False
        return self.elapsed_seconds > self.limits.max_seconds

    @property
    def steps_exceeded(self) -> bool:
        """Whether the step limit has been exceeded."""
        if self.limits.max_steps is None:
            return False
        return self._steps > self.limits.max_steps

    @property
    def tool_calls_exceeded(self) -> bool:
        """Whether the tool-call limit has been exceeded."""
        if self.limits.max_tool_calls is None:
            return False
        return self._tool_calls > self.limits.max_tool_calls

    @property
    def exhausted(self) -> bool:
        """Whether any limit has been exceeded."""
        return (
            self.time_exceeded
            or self.steps_exceeded
            or self.tool_calls_exceeded
        )


# ==============================================================================
# DURATION METRIC
# ==============================================================================


@dataclass(slots=True)
class DurationMetric:
    """
    Rolling duration statistics.
    """

    total: int = 0

    sum_ms: float = 0.0

    min_ms: float = 0.0

    max_ms: float = 0.0

    def record(self, duration_ms: float) -> None:
        """Record a duration sample."""
        self.total += 1
        self.sum_ms += duration_ms

        if self.total == 1 or duration_ms < self.min_ms:
            self.min_ms = duration_ms

        if duration_ms > self.max_ms:
            self.max_ms = duration_ms

    @property
    def average_ms(self) -> float:
        """Average duration in milliseconds."""
        if self.total == 0:
            return 0.0
        return self.sum_ms / self.total


def measure_duration(callback: Any, *args: Any, **kwargs: Any) -> tuple[Any, float]:
    """
    Synchronously execute a callable and measure its duration.

    Returns (result, duration_ms).
    """

    started = time.perf_counter()

    result = callback(*args, **kwargs)

    duration_ms = (time.perf_counter() - started) * 1000.0

    return result, duration_ms


# ==============================================================================
# PERIODIC TICKER
# ==============================================================================


class Ticker:
    """
    Emits ticks at a fixed interval for periodic monitoring loops.

    Useful for heartbeat-style reporting: call :meth:`tick` each iteration
    and act only when it returns True.

    Examples
    --------
        ticker = Ticker(interval_seconds=5)

        while running:
            work()
            if ticker.tick():
                report_progress()
    """

    def __init__(
        self,
        interval_seconds: float,
        *,
        started_at: float | None = None,
    ) -> None:

        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

        self.interval_seconds = interval_seconds
        self._next_tick = (
            started_at
            if started_at is not None
            else time.monotonic() + interval_seconds
        )

    @property
    def due(self) -> bool:
        """Whether a tick is currently due."""
        return time.monotonic() >= self._next_tick

    def tick(self) -> bool:
        """
        Consume a tick if one is due.

        Returns True exactly once per interval, then re-arms the timer.
        """
        if not self.due:
            return False

        self._next_tick = time.monotonic() + self.interval_seconds
        return True

    def reset(self) -> None:
        """Re-arm the ticker from now."""
        self._next_tick = time.monotonic() + self.interval_seconds


# ==============================================================================
# PUBLIC EXPORTS
# ==============================================================================

__all__ = [
    "Stopwatch",
    "timer",
    "async_timer",
    "Deadline",
    "check_timeout",
    "with_timeout",
    "BackoffConfig",
    "ExponentialBackoff",
    "retry_delay",
    "sleep_retry",
    "SchedulerClock",
    "BudgetLimits",
    "ExecutionBudget",
    "DurationMetric",
    "measure_duration",
    "Ticker",
]
