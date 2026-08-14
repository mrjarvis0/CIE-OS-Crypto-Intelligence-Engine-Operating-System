"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    blockchain.reorg

Purpose:
    Keeping A01's record of the chain equal to the chain that actually
    happened.

Contents:
    finality -- per-chain finality models; when a block stops being able to change
    detector -- parent-hash linkage tracking; gap, reorg and violation classification

Planned:
    rollback and reconciliation, which withdraw and re-derive affected records,
    are not implemented. They act on stored data, and A01 has no blockchain
    storage layer yet; building them now would mean writing an undo for a write
    that does not exist. ``ReorgEvent.rollback_from`` already carries the height
    they will need.
"""

from __future__ import annotations

from .detector import (
    DEFAULT_WINDOW,
    BlockRef,
    ChainTracker,
    Observation,
    ObservationResult,
    ReorgEvent,
)
from .finality import (
    FinalityModel,
    FinalityPolicy,
    all_policies,
    confirmations_for,
    finality_policy,
)

__all__ = [
    # finality
    "FinalityModel",
    "FinalityPolicy",
    "finality_policy",
    "all_policies",
    "confirmations_for",
    # detection
    "ChainTracker",
    "BlockRef",
    "ReorgEvent",
    "Observation",
    "ObservationResult",
    "DEFAULT_WINDOW",
]
