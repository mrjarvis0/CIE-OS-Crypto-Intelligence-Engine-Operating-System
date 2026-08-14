"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    ingestion.recovery

Purpose:
    Decide what a reorg means for recorded state, and repair that state -- the
    tracker's blocks and the dedup window -- so the chain can be re-walked.

Design goals:
    - Decision separated from mutation, so the refusals are testable alone
    - Two conditions refused outright rather than absorbed
    - Withdrawn blocks made re-ingestible at the same heights
    - No network I/O, no queueing, no checkpoint writes

Notes:
    Split out of the poller because it answers a different question. The poller
    asks "what should happen next"; this asks "what that was already recorded
    is now wrong, and how far back does the damage go". Keeping the second in
    the first made a 600-line module where the interesting logic -- the two
    conditions that must stop the run -- was buried in the middle of an
    ordinary loop.

    The distinction the plan turns on is whether the replacing block hangs
    directly off the common ancestor. If it does, it is simply the next block.
    If it sits higher, the heights between the ancestor and it exist only on
    the new branch and have never been read, so it must not be adopted as the
    tip -- doing so makes the following arrival look like ordinary progress and
    those heights are never asked for again.

    Checkpoint writes and queueing deliberately stay with the poller. Those are
    the two operations whose ordering decides whether a crash loses a block, and
    that ordering should be readable in one place rather than split across two
    modules.
"""

from __future__ import annotations

import logging

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from blockchain.reorg import BlockRef, ChainTracker, ReorgEvent
from core.exceptions import FinalityViolationError, IngestionError

from .dedup import SeenSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """
    What to do about one reorg, decided before anything is mutated.

    ``contiguous`` is the field the caller branches on: true means the block
    that arrived is the next block and can be delivered now, false means the
    branch has to be re-walked from :attr:`ancestor` before it is reached.
    """

    chain: str
    ancestor: int
    ancestor_hash: str
    contiguous: bool
    depth: int

    @property
    def resume_height(self) -> int:
        """The first height that must be read on the new branch."""
        return self.ancestor + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "ancestor": self.ancestor,
            "contiguous": self.contiguous,
            "depth": self.depth,
            "resume_height": self.resume_height,
        }


class ReorgRecovery:
    """
    Owns the state a reorg invalidates: tracked blocks and remembered ids.

    Holds the height-to-record-id map because that map exists for exactly one
    purpose -- letting a withdrawn block be ingested again at the same height.
    Nothing else reads it.
    """

    def __init__(
        self,
        chain: str,
        tracker: ChainTracker,
        seen: SeenSet,
    ) -> None:
        self._chain = chain
        self._tracker = tracker
        self._seen = seen
        #: height -> record id, bounded by the tracker window because a reorg
        #: cannot reach further back than the tracker can see.
        self._record_ids: OrderedDict[int, str] = OrderedDict()

    # -- id memory --------------------------------------------------------

    def remember(self, height: int, record_id: str) -> None:
        """Note which record was stored at a height, for later withdrawal."""
        self._record_ids[height] = record_id
        while len(self._record_ids) > self._tracker.window:
            self._record_ids.popitem(last=False)

    def remembered(self, height: int) -> str | None:
        return self._record_ids.get(height)

    # -- decision ---------------------------------------------------------

    def plan(self, event: ReorgEvent | None, ref: BlockRef) -> RecoveryPlan:
        """
        Decide how to recover, or refuse.

        Raises before touching anything, so a refusal leaves recorded state
        exactly as it was and the run can be resumed after a human looks at it.
        """
        if event is None:  # pragma: no cover - the tracker always attaches one
            raise IngestionError(f"{self._chain}: reorg reported without an event")

        if event.crossed_finality:
            # On a deterministic chain this cannot legitimately occur, so it is
            # evidence about the provider rather than about the chain. Rolling
            # back finalized history on that word would let one bad endpoint
            # rewrite A01's record.
            raise FinalityViolationError(
                f"{self._chain}: reorg at block {ref.number} reaches below "
                f"finalized height {event.finalized_height}; a provider is "
                "serving a different chain or lying. Finalized history will "
                "not be rewritten automatically.",
                chain=self._chain,
                depth=event.depth,
                finalized_height=event.finalized_height,
            )

        ancestor = event.common_ancestor
        if ancestor is None:
            # Depth is a lower bound, so the true fork point is unknown. Any
            # rewind would be a guess, and a wrong one leaves a hole in history
            # that nothing afterwards detects.
            raise IngestionError(
                f"{self._chain}: reorg at block {ref.number} forks below the "
                f"tracked window, so its depth is at least {event.depth} and "
                "the true fork point is unknown; resuming would risk an "
                "undetected hole in history",
                details={"chain": self._chain, "depth": event.depth},
            )

        ancestor_ref = self._tracker.get(ancestor)
        if ancestor_ref is None:  # pragma: no cover - ancestor is inside the window
            raise IngestionError(
                f"{self._chain}: common ancestor {ancestor} is not in the tracker",
                details={"chain": self._chain, "ancestor": ancestor},
            )

        return RecoveryPlan(
            chain=self._chain,
            ancestor=ancestor,
            ancestor_hash=ancestor_ref.hash,
            contiguous=ref.number == ancestor + 1,
            depth=event.depth,
        )

    # -- mutation ---------------------------------------------------------

    def apply(self, plan: RecoveryPlan, event: ReorgEvent) -> tuple[int, ...]:
        """
        Withdraw the orphaned blocks and return the heights that were dropped.

        The caller must treat those heights as deleted downstream. Returning
        them rather than logging them is deliberate: a consumer that keeps
        storage in step needs the list, and reconstructing it from a log line
        is not something a program can do.
        """
        if plan.contiguous:
            orphaned = self._tracker.accept_reorg(event)
        else:
            orphaned = self._tracker.rollback_to(plan.ancestor)

        withdrawn = tuple(orphan.number for orphan in orphaned)

        # A withdrawn block must be re-ingestible at the same height, so its id
        # leaves the dedup window; a stale entry would make the replacement look
        # like a duplicate of the block it replaces and the height would stay
        # empty.
        for height in withdrawn:
            record_id = self._record_ids.pop(height, None)
            if record_id is not None:
                self._seen.forget(record_id)

        logger.warning(
            "%s: reorg depth %d at ancestor %d, %d block(s) withdrawn",
            self._chain,
            plan.depth,
            plan.ancestor,
            len(withdrawn),
        )
        return withdrawn

    def snapshot(self) -> dict[str, Any]:
        return {
            "remembered_heights": len(self._record_ids),
            "window": self._tracker.window,
        }


__all__ = ["RecoveryPlan", "ReorgRecovery"]
