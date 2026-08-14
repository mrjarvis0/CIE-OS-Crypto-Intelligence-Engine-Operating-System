"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    tiers.retention

Purpose:
    What A01 keeps, for how long, and what it deliberately throws away.

The problem this exists to solve
--------------------------------
Storing every transaction cost **0.70 MB per ethereum block** -- measured, not
estimated: 77 blocks occupied 54.2 MB. Ethereum produces 7,200 blocks a day, so
that is roughly 5 GB per day and 150 GB per month, for one chain. Across fifteen
chains it is 30-50 GB a day.

Almost none of it was ever read. 334 transactions per block were kept so that a
handful of them could later be counted, and the counting could have happened
once, at capture.

So the rule is: **compute at the edge, keep the answer, drop the input.**

Why "keep nothing, always read live" is the wrong fix
-----------------------------------------------------
It is the obvious correction and it breaks three things at once:

1. **Baselines become impossible.** "Whale transactions: normal 1,200/day,
   today 4,800" is the signal. The comparison needs history that no live call
   can return, because the chain does not store "what was normal last week".
2. **Rate budgets get worse, not better.** Free tiers meter per day and per
   month. Recomputing from live data re-fetches blocks already seen, so the
   budget is spent twice on the same answer.
3. **Provenance stops working.** Evidence cites a record. A cited record that
   was never kept cannot be produced when the conclusion is challenged.

The tiers below keep what those three need and nothing else.

The four tiers
--------------
``CACHE``   Raw RPC responses. Seconds to minutes, in memory, never on disk.
            This is where the 0.70 MB block body lives, and where it dies.
            Already implemented: ``blockchain.rpc.clients.cache.ResponseCache``,
            whose lifetimes derive from finality rather than a fixed clock.

``HOT``     7 days. Block headers, per-block aggregates, material transactions.
            Answers "how much moved in the last four hours" and drives the live
            dashboard.

``WARM``    90 days. Hourly aggregates, 24x smaller than per-block. This is the
            baseline tier -- the reason an anomaly can be called an anomaly.
            Ninety days because institutional and smart-money patterns are
            measured in months, not days.

``LEDGER``  Never expires. One row per tracked address, its track record, and
            the labels attached to it. Smart money is a claim about history, so
            the history has to outlive every retention sweep. This tier grows
            with the number of entities A01 tracks, not with chain traffic,
            which is what makes "forever" affordable.

What is never dropped
---------------------
**Material transactions survive as long as their entity is tracked.** They are
not data, they are the evidence a conclusion cites. Compacting them would leave
A01 asserting things it could no longer show.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Final


class Tier(StrEnum):
    """Where a record lives, and therefore how long it survives."""

    #: In memory, never written. Raw provider responses.
    CACHE = "cache"
    #: Full resolution, recent. Per-block detail.
    HOT = "hot"
    #: Compacted, months. Hourly baselines.
    WARM = "warm"
    #: Permanent. Entities, track records, labels.
    LEDGER = "ledger"


#: How long full per-block detail is kept before rolling up to the hour.
#:
#: Seven days rather than the finality depth alone. Reorg safety needs only a
#: few hundred blocks, but a backfill that repairs a gap needs the surrounding
#: detail still present, and "the last week, by block" is a question a trader
#: actually asks.
HOT_WINDOW: Final[timedelta] = timedelta(days=7)

#: How long hourly aggregates are kept. The baseline horizon.
#:
#: Ninety days is the operator's stated requirement for institutional and
#: smart-money detection, and it is also roughly the shortest window in which a
#: market cycle phase is visible.
WARM_WINDOW: Final[timedelta] = timedelta(days=90)

#: Hourly aggregates compact to daily at the warm boundary, and daily are kept
#: for a year before being dropped. A year of daily rows is 365 rows per chain.
COLD_WINDOW: Final[timedelta] = timedelta(days=365)

#: Time-to-live for a cached raw block body. Short: its only job is to stop the
#: same block being fetched twice while it is being processed.
CACHE_BLOCK_TTL_SECONDS: Final[float] = 60.0

#: Market quotes -- price, market cap, liquidity, TVL. Longer than a block
#: because these providers meter aggressively and the numbers move slowly
#: relative to their own rate limits.
CACHE_QUOTE_TTL_SECONDS: Final[float] = 300.0


@dataclass(frozen=True, slots=True)
class RetentionRule:
    """
    One tier's policy, stated so it can be reported rather than inferred.

    ``keeps`` and ``drops`` are prose on purpose. A retention policy that only
    a reader of the sweep code can describe is a policy nobody audits.
    """

    tier: Tier
    window: timedelta | None
    keeps: str
    drops: str

    @property
    def permanent(self) -> bool:
        return self.window is None

    def as_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier.value,
            "window_days": None if self.permanent else self.window.days,
            "keeps": self.keeps,
            "drops": self.drops,
        }


POLICY: Final[tuple[RetentionRule, ...]] = (
    RetentionRule(
        tier=Tier.CACHE,
        window=timedelta(seconds=CACHE_BLOCK_TTL_SECONDS),
        keeps="raw provider responses, in memory only",
        drops="everything, on expiry -- including the full transaction list",
    ),
    RetentionRule(
        tier=Tier.HOT,
        window=HOT_WINDOW,
        keeps="block headers, per-block aggregates, material transactions",
        drops="nothing; per-block aggregates roll up to hourly at the boundary",
    ),
    RetentionRule(
        tier=Tier.WARM,
        window=WARM_WINDOW,
        keeps="hourly aggregates, material transactions, flow aggregates",
        drops="per-block resolution, which the hourly rollup supersedes",
    ),
    RetentionRule(
        tier=Tier.LEDGER,
        window=None,
        keeps="entities, smart-money track records, labels, provenance index",
        drops="nothing -- an entity falling quiet is itself a signal",
    ),
)


def rule_for(tier: Tier) -> RetentionRule:
    """The policy for one tier. Never raises: an unknown tier is a bug, not input."""
    for rule in POLICY:
        if rule.tier is tier:
            return rule
    raise KeyError(f"no retention rule for tier {tier!r}")


def describe() -> str:
    """One operator-facing block explaining what is kept and for how long."""
    lines = []
    for rule in POLICY:
        window = "never expires" if rule.permanent else f"{rule.window}"
        lines.append(f"{rule.tier.value:<7} {window:<20} {rule.keeps}")
    return "\n".join(lines)


__all__ = [
    "CACHE_BLOCK_TTL_SECONDS",
    "CACHE_QUOTE_TTL_SECONDS",
    "COLD_WINDOW",
    "HOT_WINDOW",
    "POLICY",
    "WARM_WINDOW",
    "RetentionRule",
    "Tier",
    "describe",
    "rule_for",
]
