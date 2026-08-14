"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    ingestion.dedup

Purpose:
    Recognise an observation A01 has already processed, so replay, overlapping
    backfills, and provider retries do not each become a separate record.

Design goals:
    - Identity from content, not from arrival order
    - Bounded memory; the window cannot grow with chain history
    - Eviction reported, so "not seen" and "no longer remembered" differ
    - No network or disk I/O

Notes:
    Duplicates are normal, not exceptional. The same block arrives again when
    a poll overlaps a backfill, when a provider is retried, when a run is
    replayed from a checkpoint, and when two endpoints are read for
    corroboration. Design rule DR-11 lists duplicate events alongside reorgs as
    ordinary blockchain conditions, so the pipeline absorbs them rather than
    treating each as an anomaly.

    The window is bounded, which means it can forget. That is a real limit and
    it is reported rather than hidden: :meth:`SeenSet.check` distinguishes a
    record that is genuinely new from one that fell out of the window, because
    the second is not proof of anything. A caller reconciling against storage
    needs to know which of the two it has.

    Memory is not the durable answer to idempotency. The database layer must
    enforce it with a unique key on the record id, because a process restart
    empties this set and any guarantee that lives only in RAM is a guarantee
    that lasts until the next deploy. This is the fast path in front of that,
    not a substitute for it.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Iterable

from sensors.envelope import RawRecord

#: Records remembered per chain. Sized to cover a deep reorg plus a poll
#: overlap, not chain history -- history-scale deduplication belongs in the
#: database, keyed on the same record id.
DEFAULT_WINDOW: Final[int] = 4096


class Seen(StrEnum):
    """What the dedup window knows about a record."""

    #: Not in the window, and the window has not evicted anything yet, so this
    #: is genuinely the first sighting.
    NEW = "new"
    #: Present in the window. A confirmed duplicate.
    DUPLICATE = "duplicate"
    #: Not in the window, but eviction has occurred, so absence proves nothing.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SeenResult:
    """Outcome of checking one record against the window."""

    state: Seen
    record_id: str

    @property
    def is_duplicate(self) -> bool:
        return self.state is Seen.DUPLICATE

    @property
    def should_process(self) -> bool:
        """
        Whether to process the record.

        ``UNKNOWN`` processes. Re-processing a record the database will reject
        on its unique key costs one wasted write; skipping a record that was
        never actually stored loses it permanently, and nothing later notices.
        """
        return self.state is not Seen.DUPLICATE

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "record_id": self.record_id}


class SeenSet:
    """
    A bounded, insertion-ordered set of record ids.

    Oldest entries are evicted first. Ordering is by insertion rather than by
    access: a record re-seen many times is not more likely to be seen again,
    so promoting it on access would evict genuinely recent entries in favour
    of a noisy one.
    """

    def __init__(self, *, window: int = DEFAULT_WINDOW) -> None:
        if window <= 0:
            raise ValueError("window must be > 0")

        self._window = window
        self._ids: OrderedDict[str, None] = OrderedDict()

        self.duplicates = 0
        self.evicted = 0

    @property
    def window(self) -> int:
        return self._window

    def __len__(self) -> int:
        return len(self._ids)

    def __contains__(self, record_id: object) -> bool:
        return record_id in self._ids

    # -- checking ---------------------------------------------------------

    def check(self, record: RawRecord | str) -> SeenResult:
        """
        Classify a record without recording it.

        Separate from :meth:`add` so a caller can decide, act, and only then
        commit. Marking a record seen before processing it means a crash
        mid-processing loses the record: the next run sees a duplicate and
        skips work that never completed.
        """
        record_id = record if isinstance(record, str) else record.record_id

        if record_id in self._ids:
            return SeenResult(Seen.DUPLICATE, record_id)
        if self.evicted:
            return SeenResult(Seen.UNKNOWN, record_id)
        return SeenResult(Seen.NEW, record_id)

    def add(self, record: RawRecord | str) -> None:
        """Record an id as processed, evicting the oldest if the window is full."""
        record_id = record if isinstance(record, str) else record.record_id

        if record_id in self._ids:
            self.duplicates += 1
            return

        self._ids[record_id] = None
        while len(self._ids) > self._window:
            self._ids.popitem(last=False)
            self.evicted += 1

    def check_and_add(self, record: RawRecord | str) -> SeenResult:
        """
        Classify and record in one step.

        For callers whose processing cannot fail partway -- an append to an
        in-memory queue, say. Anything that can fail should use
        :meth:`check` and :meth:`add` around the work.
        """
        result = self.check(record)
        if not result.is_duplicate:
            self.add(result.record_id)
        else:
            self.duplicates += 1
        return result

    def extend(self, records: Iterable[RawRecord | str]) -> None:
        for record in records:
            self.add(record)

    def forget(self, record: RawRecord | str) -> None:
        """
        Drop one id, so the record will be processed again.

        Used by reorg recovery: blocks withdrawn from the canonical chain must
        be re-ingestible at the same heights, and a stale id in the window
        would make the replacement look like a duplicate of the block it
        replaces.
        """
        record_id = record if isinstance(record, str) else record.record_id
        self._ids.pop(record_id, None)

    def clear(self) -> None:
        self._ids.clear()

    def snapshot(self) -> dict[str, Any]:
        """Operator-facing counters."""
        return {
            "tracked": len(self._ids),
            "window": self._window,
            "duplicates": self.duplicates,
            "evicted": self.evicted,
            #: True once absence stops being proof of novelty.
            "lossy": bool(self.evicted),
        }

    def __repr__(self) -> str:
        return f"SeenSet(tracked={len(self._ids)}, window={self._window})"


__all__ = ["DEFAULT_WINDOW", "Seen", "SeenResult", "SeenSet"]
