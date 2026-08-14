"""
CIE-OS
A01 Blockchain Intelligence Agent

Tests for blockchain.reorg -- finality models and chain linkage tracking.

Reorgs cannot be tested against a live chain: they are rare, unschedulable,
and the deep ones that matter most essentially never occur on demand. So the
block sequence is scripted, and every case the detector claims to distinguish
is played through it explicitly.
"""

from __future__ import annotations

import pytest

from blockchain.reorg import (
    BlockRef,
    ChainTracker,
    FinalityModel,
    Observation,
    all_policies,
    confirmations_for,
    finality_policy,
)
from config.rpc.chains import ChainName, default_registry


def block(number: int, tag: str = "a", parent_tag: str | None = None) -> BlockRef:
    """A block whose hash encodes its height and branch, so forks are readable."""
    parent = parent_tag if parent_tag is not None else tag
    return BlockRef(
        number=number,
        hash=f"0x{tag}{number:06d}",
        parent_hash=f"0x{parent}{number - 1:06d}" if number else "0x0",
    )


def chain_of(count: int, tag: str = "a", start: int = 0) -> list[BlockRef]:
    return [block(start + i, tag) for i in range(count)]


# ==============================================================================
# FINALITY POLICIES
# ==============================================================================

def test_every_registered_chain_has_a_finality_policy():
    policies = all_policies()
    for chain in default_registry():
        assert chain.name in policies, f"{chain.name.value} has no finality policy"


def test_deterministic_chains_name_a_finalized_tag():
    """
    Post-Merge Ethereum states finality outright. A deterministic policy that
    cannot say how to read it is just a confirmation count wearing a label.
    """
    for policy in all_policies().values():
        if policy.model == FinalityModel.DETERMINISTIC:
            assert policy.finalized_tag, policy.chain.value


def test_bitcoin_is_probabilistic_and_has_no_tag():
    policy = finality_policy(ChainName.BITCOIN)
    assert policy.model == FinalityModel.PROBABILISTIC
    assert policy.finalized_tag is None
    assert policy.depth_is_authoritative is True


def test_rollup_depth_is_not_authoritative():
    """
    The case a confirmation count gets actively wrong. 20 Base blocks pass in
    seconds and settle nothing; the block is only as final as its L1 batch.
    """
    for name in (ChainName.ARBITRUM, ChainName.OPTIMISM, ChainName.BASE):
        policy = finality_policy(name)
        assert policy.model == FinalityModel.SETTLED_ON_L1
        assert policy.settles_on == ChainName.ETHEREUM
        assert policy.depth_is_authoritative is False


def test_ethereum_depth_is_not_authoritative_either():
    """Ethereum finalizes deterministically; 12 confirmations is only a fallback."""
    assert finality_policy(ChainName.ETHEREUM).depth_is_authoritative is False


def test_policy_confirmations_match_the_chain_registry():
    """Two sources for the same number is how they drift apart."""
    for chain in default_registry():
        assert confirmations_for(chain.name) == chain.confirmations, chain.name.value


def test_a_chain_cannot_settle_on_itself():
    from blockchain.reorg.finality import FinalityPolicy

    with pytest.raises(ValueError, match="cannot settle on itself"):
        FinalityPolicy(
            chain=ChainName.BASE,
            model=FinalityModel.SETTLED_ON_L1,
            confirmations=20,
            settles_on=ChainName.BASE,
        )


def test_deterministic_policy_without_a_tag_is_rejected():
    from blockchain.reorg.finality import FinalityPolicy

    with pytest.raises(ValueError, match="must name its finalized tag"):
        FinalityPolicy(
            chain=ChainName.ETHEREUM,
            model=FinalityModel.DETERMINISTIC,
            confirmations=12,
        )


# ==============================================================================
# LINKAGE: NORMAL PROGRESS
# ==============================================================================

def test_first_block_is_initial():
    tracker = ChainTracker(ChainName.ETHEREUM)
    assert tracker.observe(block(100)).observation == Observation.INITIAL


def test_linked_blocks_extend_the_chain():
    tracker = ChainTracker(ChainName.ETHEREUM)
    for b in chain_of(5, start=100):
        tracker.observe(b)
    assert tracker.tip is not None
    assert tracker.tip.number == 104


def test_replaying_the_same_block_is_idempotent():
    """Backfill and live ingestion overlap at the seam; that is not an error."""
    tracker = ChainTracker(ChainName.ETHEREUM)
    tracker.observe(block(100))
    tracker.observe(block(101))

    result = tracker.observe(block(101))
    assert result.observation == Observation.DUPLICATE
    assert tracker.reorgs_seen == 0


# ==============================================================================
# LINKAGE: GAPS ARE NOT REORGS
# ==============================================================================

def test_skipped_heights_are_a_gap_not_a_reorg():
    """
    Missing data and wrong data need opposite responses. Reading a gap as a
    reorg throws away blocks that were perfectly good.
    """
    tracker = ChainTracker(ChainName.ETHEREUM)
    tracker.observe(block(100))

    result = tracker.observe(block(105))
    assert result.observation == Observation.GAP
    assert result.needs_backfill
    assert result.missing_range == (101, 104)
    assert tracker.reorgs_seen == 0


def test_gap_range_is_the_exact_set_to_backfill():
    tracker = ChainTracker(ChainName.ETHEREUM)
    tracker.observe(block(100))
    low, high = tracker.observe(block(103)).missing_range
    assert list(range(low, high + 1)) == [101, 102]


# ==============================================================================
# LINKAGE: REORG DETECTION
# ==============================================================================

def test_broken_parent_linkage_is_a_reorg():
    """
    Block numbers alone cannot see this: the replacement carries the same
    number as the block it replaces. Only the parent hash differs.
    """
    tracker = ChainTracker(ChainName.ETHEREUM)
    for b in chain_of(3, "a", start=100):
        tracker.observe(b)

    result = tracker.observe(block(103, "b"))
    assert result.is_reorg
    assert result.reorg is not None


def test_same_height_different_hash_is_a_reorg():
    tracker = ChainTracker(ChainName.ETHEREUM)
    for b in chain_of(3, "a", start=100):
        tracker.observe(b)

    result = tracker.observe(block(102, "b"))
    assert result.is_reorg


def test_reorg_reports_depth_and_rollback_point():
    tracker = ChainTracker(ChainName.ETHEREUM)
    for b in chain_of(5, "a", start=100):  # 100..104
        tracker.observe(b)

    # Branch b's block 103 descends from a's 102.
    forked = BlockRef(number=103, hash="0xb000103", parent_hash="0xa000102")
    event = tracker.observe(forked).reorg

    assert event is not None
    assert event.common_ancestor == 102
    assert event.rollback_from == 103
    assert {b.number for b in event.orphaned} == {103, 104}
    assert event.depth == 2


def test_accepting_a_reorg_drops_the_orphans_and_installs_the_new_tip():
    tracker = ChainTracker(ChainName.ETHEREUM)
    for b in chain_of(5, "a", start=100):
        tracker.observe(b)

    forked = BlockRef(number=103, hash="0xb000103", parent_hash="0xa000102")
    event = tracker.observe(forked).reorg
    assert event is not None

    tracker.accept_reorg(event)
    assert tracker.tip is not None
    assert tracker.tip.hash == "0xb000103"
    assert tracker.get(104) is None
    assert tracker.get(102) is not None


def test_detection_does_not_mutate_until_accepted():
    """
    A reorg that crossed finality must not be applied without a decision, so
    observe() reports and accept_reorg() acts.
    """
    tracker = ChainTracker(ChainName.ETHEREUM)
    for b in chain_of(3, "a", start=100):
        tracker.observe(b)

    tracker.observe(BlockRef(number=102, hash="0xb000102", parent_hash="0xa000101"))
    assert tracker.get(102) is not None
    assert tracker.get(102).hash == "0xa000102", "state changed before acceptance"


def test_deepest_reorg_is_tracked():
    tracker = ChainTracker(ChainName.ETHEREUM)
    for b in chain_of(10, "a", start=100):
        tracker.observe(b)

    tracker.observe(BlockRef(number=105, hash="0xb000105", parent_hash="0xa000104"))
    assert tracker.deepest_reorg == 5


# ==============================================================================
# FINALITY VIOLATIONS
# ==============================================================================

def test_reorg_below_the_finalized_point_is_flagged_as_a_violation():
    """
    On a deterministic chain this cannot legitimately happen. Absorbing it
    silently would let one bad endpoint rewrite finalized history.
    """
    tracker = ChainTracker(ChainName.ETHEREUM)
    for b in chain_of(10, "a", start=100):
        tracker.observe(b)
    tracker.mark_finalized(107)

    event = tracker.observe(
        BlockRef(number=105, hash="0xb000105", parent_hash="0xa000104")
    ).reorg

    assert event is not None
    assert event.crossed_finality is True
    assert event.finalized_height == 107
    assert tracker.finality_violations == 1


def test_reorg_above_the_finalized_point_is_ordinary():
    tracker = ChainTracker(ChainName.ETHEREUM)
    for b in chain_of(10, "a", start=100):
        tracker.observe(b)
    tracker.mark_finalized(103)

    event = tracker.observe(
        BlockRef(number=108, hash="0xb000108", parent_hash="0xa000107")
    ).reorg

    assert event is not None
    assert event.crossed_finality is False
    assert tracker.finality_violations == 0


def test_finalized_height_never_moves_backwards():
    """A provider reporting a lower finalized height is behind, not correct."""
    tracker = ChainTracker(ChainName.ETHEREUM)
    tracker.mark_finalized(200)
    tracker.mark_finalized(150)
    assert tracker.finalized_height == 200


# ==============================================================================
# WINDOW BOUNDS
# ==============================================================================

def test_memory_is_bounded_by_the_window():
    tracker = ChainTracker(ChainName.ETHEREUM, window=10)
    for b in chain_of(50, start=100):
        tracker.observe(b)
    assert tracker.snapshot()["tracked_blocks"] == 10


def test_block_below_the_window_cannot_be_linkage_checked():
    tracker = ChainTracker(ChainName.ETHEREUM, window=5)
    for b in chain_of(20, start=100):
        tracker.observe(b)

    result = tracker.observe(block(100, "b"))
    assert result.observation == Observation.BELOW_WINDOW


def test_fork_older_than_the_window_reports_depth_as_a_lower_bound():
    """
    Claiming an exact depth when the common ancestor was evicted would be a
    fabricated number.
    """
    tracker = ChainTracker(ChainName.ETHEREUM, window=5)
    for b in chain_of(20, "a", start=100):  # retains 115..119
        tracker.observe(b)

    event = tracker.observe(
        BlockRef(number=116, hash="0xb000116", parent_hash="0xUNKNOWN")
    ).reorg
    assert event is not None
    assert event.depth_is_lower_bound is True


# ==============================================================================
# VALIDATION
# ==============================================================================

def test_block_without_a_parent_hash_is_rejected():
    with pytest.raises(ValueError, match="no parent hash"):
        BlockRef(number=100, hash="0xabc", parent_hash="")


def test_genesis_may_have_no_parent():
    assert BlockRef(number=0, hash="0xgenesis", parent_hash="").number == 0


def test_snapshot_is_serialisable():
    import json

    tracker = ChainTracker(ChainName.ETHEREUM)
    tracker.observe(block(100))
    assert json.loads(json.dumps(tracker.snapshot()))["chain"] == "ethereum"
