"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    tiers

Purpose:
    Where on-chain data lives, and for how long.

The four tiers, shortest-lived first:

    CACHE   seconds   raw provider responses, in memory only
    HOT     7 days    per-block aggregates + material transactions
    WARM    90 days   hourly aggregates -- the baseline an anomaly is measured against
    LEDGER  forever   entities, track records, labels

The rule the whole package exists to enforce: **a full transaction list is
never written to disk.** It arrives in CACHE, is streamed through the
materiality gate in ``pipeline``, contributes to a HOT aggregate, and is
dropped. Measured cost before this: 0.70 MB per ethereum block. Target after:
under 5 KB.

``CACHE`` is not implemented here. ``blockchain.rpc.clients.cache.ResponseCache``
already does the job and does it better than a generic TTL map would -- its
lifetimes derive from finality, so an immutable block is held indefinitely while
a head-dependent read is barely held at all, and a failed call is never cached.
It is wired into ``ChainDispatcher``, so every sensor read passes through it.

See ``tiers.retention`` for the policy, stated as data rather than as behaviour.
"""

from __future__ import annotations

from .hot import BlockAggregate, BlockAggregateRepository, WindowTotals
from .ledger import (
    CATEGORIES,
    CONFIDENCE,
    EVM_SCOPE,
    UNVERIFIED,
    Label,
    LabelEntry,
    LabelRepository,
    LabelSet,
    chain_scope,
    label_set_from,
)
from .warm import ExchangeFlowHour, ExchangeFlowRepository, FlowTotals, hour_of
from .retention import (
    CACHE_BLOCK_TTL_SECONDS,
    CACHE_QUOTE_TTL_SECONDS,
    COLD_WINDOW,
    HOT_WINDOW,
    POLICY,
    WARM_WINDOW,
    RetentionRule,
    Tier,
    describe,
    rule_for,
)

__all__ = [
    "CACHE_BLOCK_TTL_SECONDS",
    "CACHE_QUOTE_TTL_SECONDS",
    "CATEGORIES",
    "COLD_WINDOW",
    "CONFIDENCE",
    "EVM_SCOPE",
    "HOT_WINDOW",
    "POLICY",
    "UNVERIFIED",
    "WARM_WINDOW",
    "BlockAggregate",
    "BlockAggregateRepository",
    "ExchangeFlowHour",
    "ExchangeFlowRepository",
    "FlowTotals",
    "Label",
    "LabelEntry",
    "LabelRepository",
    "LabelSet",
    "RetentionRule",
    "Tier",
    "WindowTotals",
    "chain_scope",
    "describe",
    "hour_of",
    "label_set_from",
    "rule_for",
]
