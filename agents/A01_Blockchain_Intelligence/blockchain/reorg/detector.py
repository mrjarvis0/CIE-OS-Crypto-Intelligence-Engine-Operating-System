"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    blockchain.reorg.detector

Purpose:
    Notice when the chain A01 recorded stops being the chain that happened.

Design goals:
    - Parent-hash linkage, not block-number comparison
    - Gaps distinguished from reorgs
    - Reorgs deeper than finality escalated, never absorbed
    - Bounded memory
    - No network I/O

Notes:
    An indexer that only tracks block numbers cannot see a reorg at all. The
    replacement block carries the same number as the one it replaced, so
    "block 100 arrived and I already have block 100" looks like a duplicate.
    Linkage is the signal: every block names its parent's hash, and the chain
    is intact exactly when that name matches what was recorded one height
    down.

    Two events are routinely confused and must not be, because the responses
    are opposite. A gap -- block 105 arriving when 100 was the last seen -- is
    missing data, and the fix is to fetch 101 through 104. A reorg is data
    that was recorded and is now wrong, and the fix is to withdraw it. Reading
    a gap as a reorg discards good data; reading a reorg as a gap keeps bad
    data and stacks the new chain on top of it.

    The case that matters most is the one that should be impossible. A reorg
    reaching deeper than the chain's finalized point is not a deep reorg to be
    handled -- on a deterministic chain it cannot happen, so observing it means
    something else is true: a provider is serving a different network, a fork
    client is out of consensus, or an endpoint is lying. Absorbing it silently
    would let A01 rewrite finalized history on the word of one bad endpoint,
    so it is surfaced as an incident and the caller decides.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from config.rpc.chains import ChainName

from .finality import FinalityPolicy, finality_policy

logger = logging.getLogger(__name__)

#: Recent blocks retained per chain. Must exceed the deepest reorg the chain
#: plausibly produces, or the common ancestor falls out of the window and the
#: depth cannot be computed. Polygon's 128-block fallback sets the floor.
DEFAULT_WINDOW: Final[int] = 512


class Observation(StrEnum):
    """What arriving at a block told us."""

    #: Parent matches the recorded tip. Normal forward progress.
    EXTENDED = "extended"
    #: Already recorded at this height with this hash. Idempotent replay.
    DUPLICATE = "duplicate"
    #: Heights were skipped. Missing data, not wrong data.
    GAP = "gap"
    #: Parent linkage broke. Recorded blocks are no longer canonical.
    REORG = "reorg"
    #: Below the tracked window, so linkage cannot be checked.
    BELOW_WINDOW = "below_window"
    #: First block seen for this chain.
    INITIAL = "initial"


@dataclass(frozen=True, slots=True)
class BlockRef:
    """The minimum needed to establish chain linkage."""

    number: int
    hash: str
    parent_hash: str

    def __post_init__(self) -> None:
        if self.number < 0:
            raise ValueError("block number must be >= 0")
        if not self.hash.strip():
            raise ValueError("block hash cannot be empty")
        # The genesis block has no meaningful parent; every other block does.
        if self.number > 0 and not self.parent_hash.strip():
            raise ValueError(f"block {self.number} has no parent hash")

    def as_dict(self) -> dict[str, Any]:
        return {"number": self.number, "hash": self.hash, "parent_hash": self.parent_hash}


@dataclass(frozen=True, slots=True)
class ReorgEvent:
    """
    A recorded chain segment that is no longer canonical.

    ``crossed_finality`` is the field that changes what a caller should do.
    False is an ordinary reorg: withdraw the orphaned blocks and re-index.
    True is an incident: on a deterministic chain it cannot legitimately
    happen, so the provider is suspect and finalized data must not be
    rewritten on its word alone.
    """

    chain: str
    depth: int
    new_tip: BlockRef
    orphaned: tuple[BlockRef, ...]
    common_ancestor: int | None
    crossed_finality: bool = False
    finalized_height: int | None = None
    #: Set when the common ancestor was not in the retained window, so depth
    #: is a lower bound rather than an exact figure.
    depth_is_lower_bound: bool = False

    @property
    def rollback_from(self) -> int:
        """Lowest block height whose recorded data must be withdrawn."""
        if self.common_ancestor is not None:
            return self.common_ancestor + 1
        return self.new_tip.number - self.depth + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "depth": self.depth,
            "depth_is_lower_bound": self.depth_is_lower_bound,
            "new_tip": self.new_tip.as_dict(),
            "orphaned": [b.as_dict() for b in self.orphaned],
            "common_ancestor": self.common_ancestor,
            "rollback_from": self.rollback_from,
            "crossed_finality": self.crossed_finality,
            "finalized_height": self.finalized_height,
        }


@dataclass(frozen=True, slots=True)
class ObservationResult:
    """Outcome of observing one block."""

    observation: Observation
    block: BlockRef
    reorg: ReorgEvent | None = None
    #: For GAP: the heights that were skipped and need backfilling.
    missing_range: tuple[int, int] | None = None

    @property
    def is_reorg(self) -> bool:
        return self.observation == Observation.REORG

    @property
    def needs_backfill(self) -> bool:
        return self.observation == Observation.GAP

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation": self.observation.value,
            "block": self.block.as_dict(),
            "reorg": self.reorg.as_dict() if self.reorg else None,
            "missing_range": list(self.missing_range) if self.missing_range else None,
        }


class ChainTracker:
    """
    Tracks one chain's recent canonical blocks and classifies each arrival.

    Deliberately passive: it reports what a block means and never fetches,
    rolls back, or writes anything. Detection has to be testable against a
    scripted block sequence, and mixing in remediation would make every test
    need a database.
    """

    def __init__(
        self,
        chain: ChainName | str,
        *,
        window: int = DEFAULT_WINDOW,
        policy: FinalityPolicy | None = None,
    ) -> None:
        if window <= 0:
            raise ValueError("window must be > 0")

        self._chain = chain.value if isinstance(chain, ChainName) else str(chain)
        self._window = window
        self._policy = policy or finality_policy(self._chain)

        #: height -> BlockRef, ordered by insertion, oldest evicted first.
        self._blocks: OrderedDict[int, BlockRef] = OrderedDict()
        #: Highest height known finalized. Never rewound.
        self._finalized_height: int | None = None

        self.reorgs_seen = 0
        self.deepest_reorg = 0
        self.finality_violations = 0

    # -- state -----------------------------------------------------------

    @property
    def chain(self) -> str:
        return self._chain

    @property
    def window(self) -> int:
        """
        How many recent blocks are retained.

        Public because it bounds what a reorg can reach: a caller keeping its
        own per-height state for recovery has no reason to remember further
        back than the tracker can see.
        """
        return self._window

    @property
    def tip(self) -> BlockRef | None:
        if not self._blocks:
            return None
        return self._blocks[max(self._blocks)]

    @property
    def finalized_height(self) -> int | None:
        return self._finalized_height

    def get(self, number: int) -> BlockRef | None:
        return self._blocks.get(number)

    def mark_finalized(self, height: int) -> None:
        """
        Record the finalized head, normally read from the ``finalized`` tag.

        Never moves backwards. A provider reporting a lower finalized height
        than one already observed is behind or wrong, and accepting it would
        reopen history that was correctly closed.
        """
        if height < 0:
            raise ValueError("finalized height must be >= 0")
        if self._finalized_height is None or height > self._finalized_height:
            self._finalized_height = height

    # -- observation -----------------------------------------------------

    def observe(self, block: BlockRef) -> ObservationResult:
        """Classify an arriving block against what has been recorded."""
        if not self._blocks:
            self._store(block)
            return ObservationResult(Observation.INITIAL, block)

        tip = self.tip
        assert tip is not None

        existing = self._blocks.get(block.number)
        if existing is not None and existing.hash == block.hash:
            return ObservationResult(Observation.DUPLICATE, block)

        # Forward progress: the common case, one past the tip with matching linkage.
        if block.number == tip.number + 1:
            if block.parent_hash == tip.hash:
                self._store(block)
                return ObservationResult(Observation.EXTENDED, block)
            return self._build_reorg(block)

        # Skipped heights. Missing data, not wrong data -- provided the
        # recorded tip is still on this block's ancestry, which cannot be
        # checked from here, so it is reported as a gap to be filled.
        if block.number > tip.number + 1:
            return ObservationResult(
                Observation.GAP,
                block,
                missing_range=(tip.number + 1, block.number - 1),
            )

        oldest = min(self._blocks)
        if block.number < oldest:
            return ObservationResult(Observation.BELOW_WINDOW, block)

        # Same height, different hash, or an older height being replaced:
        # the recorded chain from here up is no longer canonical.
        return self._build_reorg(block)

    def _build_reorg(self, block: BlockRef) -> ObservationResult:
        """Work out how deep the divergence goes and whether it is legitimate."""
        ancestor = self._find_common_ancestor(block)

        if ancestor is not None:
            orphaned = tuple(
                self._blocks[h] for h in sorted(self._blocks) if h > ancestor
            )
            depth = len(orphaned)
            lower_bound = False
        else:
            # The fork point is older than the retained window, so the true
            # depth is unknown and what we have is a floor.
            orphaned = tuple(
                self._blocks[h] for h in sorted(self._blocks) if h >= block.number
            )
            depth = max(len(orphaned), 1)
            lower_bound = True

        crossed = False
        if self._finalized_height is not None:
            rollback_from = (ancestor + 1) if ancestor is not None else block.number
            crossed = rollback_from <= self._finalized_height

        event = ReorgEvent(
            chain=self._chain,
            depth=depth,
            new_tip=block,
            orphaned=orphaned,
            common_ancestor=ancestor,
            crossed_finality=crossed,
            finalized_height=self._finalized_height,
            depth_is_lower_bound=lower_bound,
        )

        self.reorgs_seen += 1
        self.deepest_reorg = max(self.deepest_reorg, depth)

        if crossed:
            self.finality_violations += 1
            logger.error(
                "%s: reorg crossed finalized height %s (rollback from %s, depth %s) -- "
                "this cannot legitimately happen; provider or network is suspect",
                self._chain,
                self._finalized_height,
                event.rollback_from,
                depth,
            )
        else:
            logger.warning("%s: reorg depth %s at block %s", self._chain, depth, block.number)

        return ObservationResult(Observation.REORG, block, reorg=event)

    def _find_common_ancestor(self, block: BlockRef) -> int | None:
        """
        Highest recorded height still on the new block's ancestry.

        Only one link can be checked without fetching the new chain's
        intermediate blocks: whether the arriving block's parent is a block we
        recorded. That resolves the shallow reorgs that make up almost all of
        them. Deeper divergence needs the new branch walked, which is the
        caller's job -- this class does no I/O.
        """
        parent = self._blocks.get(block.number - 1)
        if parent is not None and parent.hash == block.parent_hash:
            return block.number - 1

        below = [h for h in sorted(self._blocks, reverse=True) if h < block.number - 1]
        return below[0] if below else None

    # -- mutation --------------------------------------------------------

    def accept_reorg(self, event: ReorgEvent) -> tuple[BlockRef, ...]:
        """
        Apply a reorg: drop the orphaned blocks and record the new tip.

        Separate from ``observe`` on purpose. A reorg that crossed finality
        must not be applied without a decision, and a detector that applied
        its own findings would leave no place to make one.
        """
        for orphan in event.orphaned:
            self._blocks.pop(orphan.number, None)
        self._store(event.new_tip)
        return event.orphaned

    def rollback_to(self, height: int) -> tuple[BlockRef, ...]:
        """
        Drop every recorded block above ``height``, adopting no new tip.

        The counterpart to :meth:`accept_reorg` for a fork that does not join
        directly onto the recorded chain. When the replacing block sits several
        heights above the common ancestor, adopting it as the tip would leave
        the heights between them permanently unrecorded: the tracker would
        report the next arrival as ordinary progress, and nothing would ask for
        the blocks that were skipped. Rolling back and re-walking the new branch
        from the ancestor is the only way those heights get read.
        """
        if height < 0:
            raise ValueError("rollback height must be >= 0")

        dropped = tuple(self._blocks[h] for h in sorted(self._blocks) if h > height)
        for block in dropped:
            self._blocks.pop(block.number, None)
        return dropped

    def _store(self, block: BlockRef) -> None:
        self._blocks[block.number] = block
        self._blocks.move_to_end(block.number)
        while len(self._blocks) > self._window:
            self._blocks.popitem(last=False)

    def reset(self) -> None:
        self._blocks.clear()
        self._finalized_height = None

    # -- reporting -------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Tracker state, for monitoring."""
        tip = self.tip
        return {
            "chain": self._chain,
            "tracked_blocks": len(self._blocks),
            "window": self._window,
            "tip": tip.number if tip else None,
            "finalized_height": self._finalized_height,
            "finality_model": self._policy.model.value,
            "reorgs_seen": self.reorgs_seen,
            "deepest_reorg": self.deepest_reorg,
            "finality_violations": self.finality_violations,
        }


__all__ = [
    "DEFAULT_WINDOW",
    "Observation",
    "BlockRef",
    "ReorgEvent",
    "ObservationResult",
    "ChainTracker",
]
