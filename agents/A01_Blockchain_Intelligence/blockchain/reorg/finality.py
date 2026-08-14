"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    blockchain.reorg.finality

Purpose:
    Say when a block has stopped being able to change, per chain, correctly.

Design goals:
    - Finality model per chain, not one confirmation count
    - Deterministic finality read from the chain, not guessed at
    - L2 finality tied to its settlement layer
    - No network I/O
    - Safe to import anywhere

Notes:
    ``ChainConfig.confirmations`` is a single integer, and a single integer
    cannot express what these nine chains actually do.

    Ethereum has had deterministic finality since the Merge: Casper FFG
    finalizes a checkpoint after two justified epochs, and the node will tell
    you which one via the ``finalized`` block tag. Counting 12 confirmations
    is the pre-Merge habit -- it is a probabilistic guess at something the
    chain now states outright, and it is both weaker and unnecessary.

    Bitcoin has no such tag and never will. Its finality is genuinely
    probabilistic, so a confirmation count is the correct instrument there.

    The rollups are the case a confirmation count gets actively wrong. An
    Arbitrum or Base block is sequencer-confirmed in under a second, so
    counting 20 of its own blocks takes seconds and feels final. It is not:
    the block is only as final as the L1 batch that settles it, and if
    Ethereum reorgs beneath it the rollup block goes with it. Treating L2
    depth as finality is how an indexer records a state that later ceases to
    have happened.

    So each chain declares a model, and callers ask this module rather than
    comparing block numbers themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Mapping

from config.rpc.chains import ChainName, get_chain


class FinalityModel(StrEnum):
    """How a chain decides a block can no longer change."""

    #: The chain states finality itself. Read it, do not infer it.
    DETERMINISTIC = "deterministic"
    #: Finality is a probability that rises with depth. Count confirmations.
    PROBABILISTIC = "probabilistic"
    #: Final only when the settlement layer finalizes the batch containing it.
    SETTLED_ON_L1 = "settled_on_l1"


@dataclass(frozen=True, slots=True)
class FinalityPolicy:
    """
    How to decide finality for one chain.

    ``confirmations`` remains meaningful for every model: it is the fallback
    when the authoritative signal is unavailable, which on a free tier is
    common -- many public endpoints do not serve the ``finalized`` tag.
    """

    chain: ChainName
    model: FinalityModel

    #: Depth at which the chain is treated as final when the authoritative
    #: signal cannot be obtained.
    confirmations: int

    #: Block tag that names the finalized head, when the chain has one.
    finalized_tag: str | None = None
    #: Weaker tag: justified but not yet finalized. Useful for a faster,
    #: explicitly lower-confidence read.
    safe_tag: str | None = None

    #: For rollups: the chain whose finality actually governs this one.
    settles_on: ChainName | None = None

    #: Rough wall-clock time to finality. Reported to operators so a stall is
    #: recognisable as a stall rather than assumed to be normal latency.
    typical_seconds: int | None = None

    notes: str = ""

    def __post_init__(self) -> None:
        if self.confirmations < 0:
            raise ValueError(f"{self.chain.value}: confirmations must be >= 0")
        if self.model == FinalityModel.DETERMINISTIC and not self.finalized_tag:
            raise ValueError(
                f"{self.chain.value}: a deterministic chain must name its finalized tag"
            )
        if self.model == FinalityModel.SETTLED_ON_L1 and self.settles_on is None:
            raise ValueError(
                f"{self.chain.value}: an L2 must name the chain it settles on"
            )
        if self.settles_on == self.chain:
            raise ValueError(f"{self.chain.value}: a chain cannot settle on itself")

    @property
    def has_authoritative_tag(self) -> bool:
        """Whether finality can be read rather than inferred."""
        return self.finalized_tag is not None

    def is_final_by_depth(self, block: int, head: int) -> bool:
        """
        Depth-based fallback.

        Used only when the finalized tag is unavailable. For an L2 this is
        explicitly a guess, and ``depth_is_authoritative`` says so.
        """
        return (head - block) >= self.confirmations

    @property
    def depth_is_authoritative(self) -> bool:
        """
        Whether counting confirmations actually establishes finality.

        False for rollups: their own block depth says nothing about whether
        the settling batch has finalized on L1.
        """
        return self.model == FinalityModel.PROBABILISTIC

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain.value,
            "model": self.model.value,
            "confirmations": self.confirmations,
            "finalized_tag": self.finalized_tag,
            "safe_tag": self.safe_tag,
            "settles_on": self.settles_on.value if self.settles_on else None,
            "typical_seconds": self.typical_seconds,
            "depth_is_authoritative": self.depth_is_authoritative,
        }


# ==============================================================================
# POLICIES
# ==============================================================================

_POLICIES: Final[dict[ChainName, FinalityPolicy]] = {
    ChainName.ETHEREUM: FinalityPolicy(
        chain=ChainName.ETHEREUM,
        model=FinalityModel.DETERMINISTIC,
        confirmations=12,
        finalized_tag="finalized",
        safe_tag="safe",
        typical_seconds=13 * 60,
        notes=(
            "Casper FFG finalizes after two justified epochs, roughly 13 minutes. "
            "The 12-confirmation figure is the pre-Merge probabilistic habit and is "
            "kept only as a fallback for endpoints that do not serve the tag."
        ),
    ),
    ChainName.BNB_CHAIN: FinalityPolicy(
        chain=ChainName.BNB_CHAIN,
        model=FinalityModel.DETERMINISTIC,
        confirmations=15,
        finalized_tag="finalized",
        safe_tag="safe",
        typical_seconds=8,
        notes="Fast finality; finalized typically two to three blocks behind head.",
    ),
    ChainName.POLYGON: FinalityPolicy(
        chain=ChainName.POLYGON,
        model=FinalityModel.DETERMINISTIC,
        confirmations=128,
        finalized_tag="finalized",
        safe_tag="safe",
        typical_seconds=5 * 60,
        notes=(
            "The 128-block figure predates the finalized tag and reflects how deep "
            "Polygon reorgs have historically run. Kept as the fallback because it "
            "is the one number here that was set by observed reorg depth."
        ),
    ),
    ChainName.ARBITRUM: FinalityPolicy(
        chain=ChainName.ARBITRUM,
        model=FinalityModel.SETTLED_ON_L1,
        confirmations=20,
        finalized_tag="finalized",
        safe_tag="safe",
        settles_on=ChainName.ETHEREUM,
        typical_seconds=15 * 60,
        notes=(
            "Sequencer-confirmed in well under a second, which is what makes depth "
            "counting dangerous here: 20 Arbitrum blocks pass in seconds and settle "
            "nothing. Real finality follows the L1 batch."
        ),
    ),
    ChainName.OPTIMISM: FinalityPolicy(
        chain=ChainName.OPTIMISM,
        model=FinalityModel.SETTLED_ON_L1,
        confirmations=20,
        finalized_tag="finalized",
        safe_tag="safe",
        settles_on=ChainName.ETHEREUM,
        typical_seconds=15 * 60,
        notes="OP Stack; finalized tracks the L1 batch, not local depth.",
    ),
    ChainName.BASE: FinalityPolicy(
        chain=ChainName.BASE,
        model=FinalityModel.SETTLED_ON_L1,
        confirmations=20,
        finalized_tag="finalized",
        safe_tag="safe",
        settles_on=ChainName.ETHEREUM,
        typical_seconds=15 * 60,
        notes="OP Stack, same settlement model as Optimism.",
    ),
    ChainName.AVALANCHE: FinalityPolicy(
        chain=ChainName.AVALANCHE,
        model=FinalityModel.DETERMINISTIC,
        confirmations=12,
        finalized_tag="finalized",
        safe_tag="safe",
        typical_seconds=2,
        notes=(
            "Snowman consensus finalizes in about a second, so the 12-confirmation "
            "fallback is far more conservative than the chain requires."
        ),
    ),
    # -- the six chains added after the first nine -------------------------
    #
    # Every tag named below was read live before it was claimed here, because
    # `finalized_tag` is an assertion that the tag answers and answers usefully.
    # The depths quoted in the notes are single observations, not averages.
    ChainName.LINEA: FinalityPolicy(
        chain=ChainName.LINEA,
        model=FinalityModel.SETTLED_ON_L1,
        confirmations=20,
        finalized_tag="finalized",
        safe_tag="safe",
        settles_on=ChainName.ETHEREUM,
        typical_seconds=3 * 60 * 60,
        notes=(
            "Observed finalized 1,202 blocks behind head, about three hours at the "
            "measured 8.4s block time -- far longer than an optimistic rollup, which "
            "is what a validity proof cycle costs. Linea returned the same block for "
            "safe and finalized, so the safe tag buys no latency here."
        ),
    ),
    ChainName.SCROLL: FinalityPolicy(
        chain=ChainName.SCROLL,
        model=FinalityModel.SETTLED_ON_L1,
        confirmations=20,
        # Deliberately absent, and this is the one policy here set by a
        # measurement that contradicted the obvious choice. Scroll answers the
        # finalized tag with a block 18.9 million behind its own head -- 45% of
        # the chain -- and answers the safe tag with null. A tag that returns a
        # number is not a tag that returns finality, and reading that one as
        # authoritative would mark two years of settled history unfinalized.
        finalized_tag=None,
        safe_tag=None,
        settles_on=ChainName.ETHEREUM,
        typical_seconds=3 * 60 * 60,
        notes=(
            "No usable finality tag: finalized reads 18.9M blocks behind head and "
            "safe reads null. Depth is the only available instrument and it is not "
            "authoritative for a rollup, so finality on Scroll is unestablished "
            "rather than approximated."
        ),
    ),
    ChainName.GNOSIS: FinalityPolicy(
        chain=ChainName.GNOSIS,
        model=FinalityModel.DETERMINISTIC,
        confirmations=32,
        finalized_tag="finalized",
        safe_tag="safe",
        typical_seconds=5 * 60,
        notes=(
            "Gasper over 16-slot epochs, so finality lands two epochs back. Observed "
            "46 blocks behind head, about four minutes at 5.1s blocks."
        ),
    ),
    ChainName.CELO: FinalityPolicy(
        chain=ChainName.CELO,
        model=FinalityModel.SETTLED_ON_L1,
        confirmations=20,
        finalized_tag="finalized",
        safe_tag="safe",
        settles_on=ChainName.ETHEREUM,
        typical_seconds=25 * 60,
        notes=(
            "An Ethereum L2 since its migration, so depth here settles nothing. "
            "Observed finalized 1,400 blocks behind head -- at one-second blocks the "
            "20-confirmation fallback is twenty seconds, which is why it must not be "
            "read as finality."
        ),
    ),
    ChainName.MANTLE: FinalityPolicy(
        chain=ChainName.MANTLE,
        model=FinalityModel.SETTLED_ON_L1,
        confirmations=20,
        finalized_tag="finalized",
        safe_tag="safe",
        settles_on=ChainName.ETHEREUM,
        typical_seconds=25 * 60,
        notes="Observed finalized 855 blocks behind head, about 28 minutes at 2s blocks.",
    ),
    ChainName.UNICHAIN: FinalityPolicy(
        chain=ChainName.UNICHAIN,
        model=FinalityModel.SETTLED_ON_L1,
        confirmations=20,
        finalized_tag="finalized",
        safe_tag="safe",
        settles_on=ChainName.ETHEREUM,
        typical_seconds=25 * 60,
        notes=(
            "OP Stack. Observed finalized 1,624 blocks behind head, about 27 minutes "
            "at one-second blocks."
        ),
    ),
    ChainName.SOLANA: FinalityPolicy(
        chain=ChainName.SOLANA,
        model=FinalityModel.DETERMINISTIC,
        confirmations=32,
        finalized_tag="finalized",
        safe_tag="confirmed",
        typical_seconds=13,
        notes=(
            "Commitment levels rather than block tags: processed, confirmed, "
            "finalized. Roughly 32 slots to finalized."
        ),
    ),
    ChainName.BITCOIN: FinalityPolicy(
        chain=ChainName.BITCOIN,
        model=FinalityModel.PROBABILISTIC,
        confirmations=6,
        finalized_tag=None,
        safe_tag=None,
        typical_seconds=60 * 60,
        notes=(
            "Genuinely probabilistic -- there is no finality tag and there never "
            "will be. Six confirmations is the convention, roughly an hour. This is "
            "the one chain where counting depth is the correct instrument."
        ),
    ),
}


def finality_policy(chain: ChainName | str) -> FinalityPolicy:
    """The finality policy for a chain."""
    key = chain if isinstance(chain, ChainName) else ChainName(str(chain).lower())
    try:
        return _POLICIES[key]
    except KeyError as exc:  # pragma: no cover - registry and policies are in sync
        raise KeyError(f"No finality policy for chain: {chain!r}") from exc


def all_policies() -> Mapping[ChainName, FinalityPolicy]:
    return dict(_POLICIES)


def confirmations_for(chain: ChainName | str) -> int:
    """
    Fallback confirmation depth for a chain.

    Prefers the finality policy and falls back to the chain registry, so the
    two cannot silently diverge.
    """
    try:
        return finality_policy(chain).confirmations
    except KeyError:  # pragma: no cover - defensive
        return get_chain(chain).confirmations


__all__ = [
    "FinalityModel",
    "FinalityPolicy",
    "finality_policy",
    "all_policies",
    "confirmations_for",
]
