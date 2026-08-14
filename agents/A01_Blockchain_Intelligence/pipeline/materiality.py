"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    pipeline.materiality

Purpose:
    Decide, one transaction at a time, whether a transaction is worth keeping.

    This is the gate that prevents the duplication problem. Everything it
    rejects contributes to a counter and is then dropped; only what it accepts
    reaches storage.

Design goals:
    - Percentile-based, never a fixed currency amount
    - Every verdict states which rule fired and why
    - The floor in force is reportable, so a quiet chain and a raised gate are
      distinguishable
    - Pure: no network, no storage lookups on the hot path
    - Cheap enough to run on every transaction of every block

Notes:
    A fixed dollar threshold is the obvious design and it is wrong in both
    directions at once. "Over $1M" is noise on Ethereum and unreachable on a
    long-tail token, so one number cannot serve both, and a number chosen for
    today is wrong after any large price move. The floor here is a **percentile
    against the chain's own recent distribution**, which is the same reasoning
    ``intelligence.analysis.whale`` already applies to whale detection.

    Size is not the only thing that makes a transaction material. A modest
    transfer into a known exchange deposit address is a stronger signal than a
    large transfer between two wallets of the same owner, so a labelled
    counterparty qualifies a transaction regardless of value. That rule is
    wired here and **currently inert**: it needs the ``labels`` table
    populated, and no label source is configured yet. It reports itself as
    unavailable rather than silently never firing.

    The floor is deliberately allowed to move. When a rate budget runs low the
    gate rises, keeping fewer transactions rather than failing the capture.
    That is a real loss of resolution, so the floor travels with every block
    aggregate and any consumer can see what was in force.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Final, Sequence

from schemas.amount import Amount

#: Percentile of the recent value distribution a transfer must reach.
#:
#: 99.5 rather than the whale detector's 99.9: this gate feeds the detectors
#: rather than replacing them, so it is deliberately wider than any single
#: detector's threshold. A gate tighter than its consumers would starve them.
DEFAULT_PERCENTILE: Final[float] = 99.5

#: Smallest population from which a percentile floor is credible. Below this the
#: cold-start floor is used instead, because a percentile over forty
#: observations is an accident rather than a threshold.
MIN_POPULATION: Final[int] = 200


class Verdict(StrEnum):
    """Why a transaction was kept, or why it was not."""

    #: Cleared the value floor.
    VALUE = "value"
    #: Touches a labelled address -- exchange, bridge, known entity.
    LABELLED = "labelled"
    #: A stablecoin movement above the floor: buying power entering or leaving.
    STABLECOIN = "stablecoin"
    #: Kept nothing back, contributed to counters only.
    IMMATERIAL = "immaterial"


@dataclass(frozen=True, slots=True)
class Decision:
    """
    One transaction's outcome.

    ``reason`` exists so a rejected transaction can be explained without
    re-running the gate, which matters when someone asks why a move they
    watched happen is not in the evidence.
    """

    material: bool
    verdict: Verdict
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "material": self.material,
            "verdict": self.verdict.value,
            "reason": self.reason,
        }


IMMATERIAL: Final[Decision] = Decision(
    material=False,
    verdict=Verdict.IMMATERIAL,
    reason="below the floor and touching no labelled address",
)


def floor_from(
    population: Sequence[int],
    *,
    percentile: float = DEFAULT_PERCENTILE,
    cold_start: Amount,
) -> Amount:
    """
    The value floor implied by a recent distribution.

    Falls back to ``cold_start`` when the population is too small to imply
    anything. That fallback is the honest answer rather than a convenience: a
    percentile computed over a handful of transfers produces a threshold that
    looks principled and is not, and it would be applied to every subsequent
    block.

    Zero-value transfers are excluded before ranking. Contract calls that move
    nothing are the bulk of chain traffic, and leaving them in drags every
    percentile down until routine transfers clear it.
    """
    if not 0.0 < percentile < 100.0:
        raise ValueError(f"percentile must be within (0, 100): {percentile}")

    values = sorted(value for value in population if value > 0)
    if len(values) < MIN_POPULATION:
        return cold_start

    # Nearest-rank. Deliberately not interpolating: the floor should be a value
    # the chain actually produced, so that "above the floor" names a real
    # observation rather than a point between two of them.
    rank = max(1, int(round(percentile / 100.0 * len(values))))
    return Amount(values[min(rank, len(values)) - 1])


class MaterialityGate:
    """
    Applies the keep-or-drop decision.

    ``is_labelled`` is injected rather than queried here so the hot path stays
    pure and testable. In production it is backed by an in-memory set loaded
    from the ``labels`` table once per run; a per-transaction database lookup
    would put a query between every transaction and its verdict.
    """

    def __init__(
        self,
        *,
        floor: Amount,
        is_labelled: Callable[[str], bool] | None = None,
        stablecoins: frozenset[str] = frozenset(),
    ) -> None:
        if floor.raw < 0:
            raise ValueError("floor cannot be negative")
        self._floor = floor
        self._is_labelled = is_labelled
        self._stablecoins = frozenset(address.lower() for address in stablecoins)

    @property
    def floor(self) -> Amount:
        return self._floor

    @property
    def labels_available(self) -> bool:
        """
        Whether the labelled-address rule can fire at all.

        False means exchange and bridge flows are invisible to this gate, which
        is a coverage limitation and not a quiet one -- callers report it.
        """
        return self._is_labelled is not None

    def assess(
        self,
        *,
        value: int,
        from_address: str | None = None,
        to_address: str | None = None,
        token: str | None = None,
    ) -> Decision:
        """Keep or drop one transaction. Never raises: a bad field is not material."""
        if value >= self._floor.raw and value > 0:
            return Decision(
                material=True,
                verdict=Verdict.VALUE,
                reason=f"value {value} at or above floor {self._floor.raw}",
            )

        if self._stablecoins and token and token.lower() in self._stablecoins:
            if value >= self._floor.raw:
                return Decision(
                    material=True,
                    verdict=Verdict.STABLECOIN,
                    reason=f"stablecoin {token} movement above floor",
                )

        if self._is_labelled is not None:
            for address in (from_address, to_address):
                if address and self._is_labelled(address):
                    return Decision(
                        material=True,
                        verdict=Verdict.LABELLED,
                        reason=f"counterparty {address} is labelled",
                    )

        return IMMATERIAL

    def limitation(self) -> str:
        """One line naming what this gate cannot currently see, or empty."""
        if not self.labels_available:
            return (
                "no address labels loaded; exchange, bridge and known-entity "
                "flows below the value floor are not captured"
            )
        return ""

    def with_floor(self, floor: Amount) -> "MaterialityGate":
        """A gate at a different floor. Used when a rate budget forces a rise."""
        return MaterialityGate(
            floor=floor,
            is_labelled=self._is_labelled,
            stablecoins=self._stablecoins,
        )

    def __repr__(self) -> str:
        return (
            f"MaterialityGate(floor={self._floor.raw}, "
            f"labels={'yes' if self.labels_available else 'no'})"
        )


__all__ = [
    "DEFAULT_PERCENTILE",
    "IMMATERIAL",
    "MIN_POPULATION",
    "Decision",
    "MaterialityGate",
    "Verdict",
    "floor_from",
]
