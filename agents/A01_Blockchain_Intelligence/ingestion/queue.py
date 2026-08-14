"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    ingestion.queue

Purpose:
    Hold captured records between the poller that produces them and the
    consumer that stores them, with a bound that makes backpressure visible.

Design goals:
    - Fixed capacity; memory cannot grow without limit when a consumer stalls
    - Overflow is a reported decision, never a silent drop
    - FIFO, so height order survives the hand-off
    - No threading primitives; the loop owns concurrency, not the buffer

Notes:
    The capacity exists because the failure it prevents is quiet. An unbounded
    queue in front of a stalled consumer does not fail -- it grows, and the
    process is killed by the OS somewhere unrelated, long after the actual
    stall. A bounded queue turns that into a counter that crosses zero at the
    moment the stall begins.

    What to do on overflow is the caller's decision, not this class's, because
    the right answer differs by record. Dropping the oldest block loses history
    permanently; dropping the newest costs only a re-fetch, since the poller
    will see that height again. The default is therefore
    :attr:`Overflow.REJECT`, which refuses the write and lets the poller stop
    advancing -- the only option that loses nothing.

    Deliberately not thread-safe and deliberately not async. The ingestion loop
    is a single stepped driver, and adding locks here would imply a concurrency
    model the layer does not have.
"""

from __future__ import annotations

import logging

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Final, Generic, Iterator, TypeVar

logger = logging.getLogger(__name__)

#: Records buffered before backpressure applies. Roughly a minute of Ethereum
#: blocks, which is long enough to ride out a slow write and short enough that
#: a real stall is noticed immediately.
DEFAULT_CAPACITY: Final[int] = 512

T = TypeVar("T")


class Overflow(StrEnum):
    """What a full queue does with a new item."""

    #: Refuse the write. The producer stops advancing; nothing is lost.
    REJECT = "reject"
    #: Discard the oldest item to make room. Loses the earliest history.
    DROP_OLDEST = "drop_oldest"
    #: Discard the incoming item. Loses the newest, which is re-fetchable.
    DROP_NEWEST = "drop_newest"


@dataclass(frozen=True, slots=True)
class PutResult:
    """Outcome of one enqueue."""

    accepted: bool
    dropped: Any = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "reason": self.reason}


class RecordQueue(Generic[T]):
    """
    Bounded FIFO buffer between capture and storage.

    Tracks its own high-water mark, because the useful question after an
    incident is not how full the queue is now but how full it got.
    """

    def __init__(
        self,
        *,
        capacity: int = DEFAULT_CAPACITY,
        on_overflow: Overflow = Overflow.REJECT,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")

        self._capacity = capacity
        self._policy = on_overflow
        self._items: deque[T] = deque()

        self.accepted = 0
        self.rejected = 0
        self.dropped = 0
        self.discarded = 0
        self.high_water = 0

    # -- state ------------------------------------------------------------

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def policy(self) -> Overflow:
        return self._policy

    @property
    def is_full(self) -> bool:
        return len(self._items) >= self._capacity

    @property
    def is_empty(self) -> bool:
        return not self._items

    @property
    def pressure(self) -> float:
        """Occupancy as a fraction of capacity, for metrics and alerting."""
        return len(self._items) / self._capacity

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    # -- writing ----------------------------------------------------------

    def put(self, item: T) -> PutResult:
        """Enqueue one record, applying the overflow policy if full."""
        if not self.is_full:
            return self._accept(item)

        if self._policy is Overflow.REJECT:
            self.rejected += 1
            return PutResult(
                accepted=False,
                reason=f"queue full at {self._capacity}; producer must wait",
            )

        if self._policy is Overflow.DROP_NEWEST:
            self.dropped += 1
            logger.warning("queue full at %d; dropped incoming record", self._capacity)
            return PutResult(
                accepted=False, dropped=item, reason="dropped newest, queue full"
            )

        oldest = self._items.popleft()
        self.dropped += 1
        logger.warning("queue full at %d; evicted oldest record", self._capacity)
        result = self._accept(oldest_dropped=oldest, item=item)
        return result

    def _accept(self, item: T, oldest_dropped: T | None = None) -> PutResult:
        self._items.append(item)
        self.accepted += 1
        self.high_water = max(self.high_water, len(self._items))
        return PutResult(accepted=True, dropped=oldest_dropped)

    # -- reading ----------------------------------------------------------

    def get(self) -> T | None:
        """The oldest record, or None when empty."""
        return self._items.popleft() if self._items else None

    def drain(self, limit: int | None = None) -> list[T]:
        """
        Remove and return up to ``limit`` records, oldest first.

        A batch read, because storage writes amortise far better in batches
        than one row at a time.
        """
        if limit is not None and limit <= 0:
            raise ValueError("limit must be > 0 when provided")

        count = len(self._items) if limit is None else min(limit, len(self._items))
        return [self._items.popleft() for _ in range(count)]

    def peek(self) -> T | None:
        return self._items[0] if self._items else None

    def discard(self, predicate: Callable[[T], bool]) -> int:
        """
        Remove every buffered item matching ``predicate``. Returns how many.

        Exists for one situation, and it is a situation that is easy to miss: a
        reorg can invalidate records that are still in this queue, captured
        before the fork was discovered and not yet stored. Storing them
        afterwards would write blocks the chain has abandoned, marked canonical,
        with nothing to indicate they are stale -- the withdrawal already ran
        against rows that had not been written yet.

        Draining is not a substitute. The stale records are indistinguishable
        from live ones once they leave the queue, so they have to be dropped
        while their heights are still known.
        """
        kept = [item for item in self._items if not predicate(item)]
        removed = len(self._items) - len(kept)
        if removed:
            self._items = deque(kept)
            self.discarded += removed
        return removed

    def clear(self) -> None:
        self._items.clear()

    # -- reporting ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "depth": len(self._items),
            "capacity": self._capacity,
            "pressure": round(self.pressure, 3),
            "high_water": self.high_water,
            "policy": self._policy.value,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "dropped": self.dropped,
            "discarded": self.discarded,
        }

    def __repr__(self) -> str:
        return f"RecordQueue(depth={len(self._items)}, capacity={self._capacity})"


__all__ = ["DEFAULT_CAPACITY", "Overflow", "PutResult", "RecordQueue"]
