"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.base

Purpose:
    The contract every skill implements, and the coverage record that keeps a
    skill's answer honest about the history it was computed from.

Design goals:
    - One skill, one responsibility; skills never call other skills
    - Every result states the window it was derived from
    - Negative claims licensed by coverage, not asserted from thin data
    - Typed input and output; independently testable against a fixture database
    - Reads storage only; a skill never fetches from a chain

Notes:
    The failure this module exists to prevent is the one that would otherwise
    make the whole read side untrustworthy. A skill answers from the database,
    and the database holds only what was ingested. Ask "is this wallet dormant"
    of a database containing four blocks and the honest answer is "unknown"; the
    naive answer is "yes, no activity found" -- for every address on Ethereum.

    Absence of evidence in a 4-block window is not evidence of absence, and
    nothing in the number itself shows the difference. So
    :class:`Coverage` travels with every result, and
    :attr:`Coverage.supports_absence` is what a skill must consult before
    reporting that something did *not* happen. A skill that reports a negative
    without checking it is the bug, not the caller who believed it.

    Not every negative is unqualified, and treating them all that way costs
    real claims. Selective capture keeps every transaction at or above a stated
    floor and drops what is below it, so a window of filtered blocks cannot say
    "nothing happened" but can say "nothing at or above this value happened" --
    which is most of what anyone asks. :attr:`Coverage.supports_bounded_absence`
    and :attr:`Coverage.absence_floor` are that claim and its edge. The
    unqualified property stays the default and stays strict: a bounded claim
    mistaken for an unbounded one is the failure, while the reverse costs only a
    claim that could have been made.

    Skills read; they never fetch. A skill that reached for an RPC would make
    its result depend on network conditions at query time, so the same question
    would get different answers for reasons unrelated to the chain -- and it
    would put an unbounded latency inside what is supposed to be a lookup.
    Filling gaps is ``ingestion``'s job, and a gap is reported here rather than
    papered over.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Final

from database.analytics import HeightWindow, SqliteAnalyticsRepository
from schemas.address import Address
from schemas.amount import Amount

#: Blocks of stored history below which no negative claim is licensed. Twelve
#: hours of Ethereum at 12s blocks: long enough that "no activity" means
#: something, short enough to be reachable by a modest backfill.
MIN_BLOCKS_FOR_ABSENCE: Final[int] = 3_600


@dataclass(frozen=True, slots=True)
class Coverage:
    """
    What the stored window licenses a skill to claim.

    Derived from a :class:`~database.analytics.HeightWindow` rather than
    duplicating it, because the question here is narrower: not "what was
    stored" but "what may be concluded from it".
    """

    window: HeightWindow
    #: Blocks required before a negative claim is permitted.
    threshold: int = MIN_BLOCKS_FOR_ABSENCE

    @property
    def blocks(self) -> int:
        return self.window.blocks

    @property
    def empty(self) -> bool:
        return self.window.empty

    @property
    def supports_absence(self) -> bool:
        """
        Whether "this did not happen" is a claim the window can carry.

        Requires depth, contiguity, and completeness -- three different ways
        the same claim can fail, and no two of them substitute for the third.

        Depth alone is not enough: a window with holes has blocks that were
        never stored, so the event may sit in a gap, and a count from it is a
        floor rather than a total.

        Contiguity is not enough either, and that was the harder one to see. A
        window can hold every height in its span and still be worthless for a
        negative claim, because a height being *present* says nothing about it
        being *whole*. A block whose logs were requested and refused is stored,
        canonical, and contiguous with its neighbours, while containing none of
        the transfers it actually emitted. Counting it toward an absence is how
        "no transfers for this address" gets asserted from a fetch that never
        happened.

        Unqualified, and it stays that way. This is the property a caller with
        no floor in hand should ask, and it answers for the whole window
        including everything below any floor. The bounded form is
        :attr:`supports_absence_above`, which a caller has to name a value to
        use -- the asymmetry is deliberate, because a bounded claim read as an
        unbounded one is the mistake, never the reverse.
        """
        return self.supports_bounded_absence and self.window.all_complete

    @property
    def supports_bounded_absence(self) -> bool:
        """
        Whether the window can carry a negative claim *above its capture floor*.

        Selective capture is why this exists. A window whose blocks were each
        filtered at a stated floor is missing transactions -- so
        :attr:`supports_absence` is false and must stay false -- but it is not
        missing them the way a refused fetch is. What was dropped is known: it
        was everything below the floor, and everything at or above it was kept.
        That licenses a real claim with a stated edge, and treating it as
        licensing nothing throws away the entire point of capturing selectively.

        Depth and contiguity are still required, unchanged. Only completeness is
        relaxed, and only as far as :attr:`~database.analytics.HeightWindow.all_captured`
        -- one unfetched block anywhere in the window closes this too.
        """
        return (
            self.window.contiguous
            and self.window.all_captured
            and self.blocks >= self.threshold
        )

    @property
    def absence_floor(self) -> Amount | None:
        """
        The value at or above which a negative claim holds; None if none does.

        ``Amount(0)`` means no floor was in force -- the window was captured
        whole, and "at or above zero" is every transfer there is. Callers that
        want that distinction spelled out should read :attr:`supports_absence`,
        which is exactly this floor being zero.
        """
        if not self.supports_bounded_absence:
            return None
        return self.window.capture_floor or Amount(0)

    def supports_absence_above(self, value: Amount) -> bool:
        """
        Whether "no transfer of at least ``value`` happened" is carryable.

        The question a caller actually has, phrased so it cannot be answered by
        accident: a threshold at or above the capture floor is answerable, one
        below it is not, and the window says which.
        """
        floor = self.absence_floor
        return floor is not None and value.raw >= floor.raw

    @property
    def limitation(self) -> str:
        """One line naming what this coverage cannot support, or empty."""
        if self.empty:
            return "no history stored for this chain"
        if not self.window.contiguous:
            return (
                f"stored history has gaps ({self.blocks} of "
                f"{self.window.span} heights); counts are floors, not totals"
            )
        if self.window.unfetched_blocks:
            # Reported ahead of depth because it is the harder failure. More
            # ingestion fixes a short window; it does not fix a stored block
            # whose logs were never fetched, which has to be captured again.
            #
            # Counted over unfetched blocks specifically. Counting every
            # incomplete block here was the bug: it told an operator that
            # selectively captured blocks had "never been fetched", which is
            # both false and the kind of false that sends someone hunting a
            # transport failure that never happened.
            return (
                f"{self.window.unfetched_blocks} of {self.blocks} stored blocks "
                "are incomplete; their transfers were never fetched, so an "
                "absence over this window is not evidence"
            )
        if self.blocks < self.threshold:
            return (
                f"only {self.blocks} blocks stored, {self.threshold} needed "
                "before an absence means anything"
            )
        if self.window.capture_floor is not None:
            # Reported after depth, because it is a qualifier rather than a
            # refusal: the window carries a negative claim, it just carries a
            # narrower one than the caller may have assumed.
            return (
                f"{self.window.selective_blocks} of {self.blocks} blocks were "
                f"captured selectively at a floor of {self.window.capture_floor.raw}; "
                "an absence is evidence at or above that floor, not below it"
            )
        return ""

    def as_dict(self) -> dict[str, Any]:
        floor = self.absence_floor
        return {
            "window": self.window.as_dict(),
            "blocks": self.blocks,
            "threshold": self.threshold,
            "supports_absence": self.supports_absence,
            "supports_bounded_absence": self.supports_bounded_absence,
            "absence_floor": str(floor.raw) if floor is not None else None,
            "limitation": self.limitation,
        }


@dataclass(frozen=True, slots=True)
class SkillRequest:
    """
    What a skill is being asked about.

    ``address`` is optional because not every skill is address-scoped -- a flow
    skill answers for a chain and a window.
    """

    chain: str
    address: Address | None = None
    from_height: int | None = None
    to_height: int | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.chain.strip():
            raise ValueError("skill request must name a chain")
        if self.address is not None and self.address.chain != self.chain:
            raise ValueError(
                f"address is on {self.address.chain}, request is for {self.chain}"
            )
        if (
            self.from_height is not None
            and self.to_height is not None
            and self.to_height < self.from_height
        ):
            raise ValueError("request height range is inverted")

    def option(self, name: str, default: Any = None) -> Any:
        return self.options.get(name, default)

    def as_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "address": self.address.value if self.address else None,
            "from_height": self.from_height,
            "to_height": self.to_height,
            "options": dict(self.options),
        }


@dataclass(frozen=True, slots=True)
class SkillResult:
    """
    One skill's answer, with the coverage that qualifies it.

    ``determined`` is false when storage could not answer at all. It is kept
    apart from an answer of zero for the same reason the sensor layer keeps
    them apart: "the window holds no such transfer" and "there is no such
    transfer" are different claims, and only one of them is usually true.
    """

    skill: str
    determined: bool
    coverage: Coverage
    data: dict[str, Any] = field(default_factory=dict)
    #: Fields this result contributes to an analyzer subject. Kept separate
    #: from ``data`` so a skill's own reporting shape can change without
    #: breaking the composition contract.
    subject: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.determined and bool(self.subject)

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "determined": self.determined,
            "reason": self.reason,
            "coverage": self.coverage.as_dict(),
            "data": self.data,
        }


class Skill(ABC):
    """
    Base class for every capability in the skills layer.

    A skill takes a request and a read repository, and returns a result. It
    does not decide what the result means, whether it is interesting, or what
    should happen next; combining skills into a judgement is the job of
    ``intelligence/``.
    """

    #: Stable identifier, used in registries, subjects, and logs.
    name: str = "skill"

    #: One line stating what this skill answers, for `cli skills`.
    description: str = ""

    def __init__(self, *, absence_threshold: int = MIN_BLOCKS_FOR_ABSENCE) -> None:
        if absence_threshold <= 0:
            raise ValueError("absence_threshold must be > 0")
        self._absence_threshold = absence_threshold

    @abstractmethod
    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        """Answer the request from stored history."""

    # -- helpers ----------------------------------------------------------

    def coverage_for(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> Coverage:
        """Coverage for the chain this request names."""
        return Coverage(
            window=analytics.window(request.chain),
            threshold=self._absence_threshold,
        )

    def undetermined(self, coverage: Coverage, reason: str) -> SkillResult:
        """A result stating that storage could not answer."""
        return SkillResult(
            skill=self.name,
            determined=False,
            coverage=coverage,
            reason=reason,
        )

    def answer(
        self,
        coverage: Coverage,
        data: dict[str, Any],
        subject: dict[str, Any],
        reason: str = "",
    ) -> SkillResult:
        return SkillResult(
            skill=self.name,
            determined=True,
            coverage=coverage,
            data=data,
            subject=subject,
            reason=reason,
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"


__all__ = [
    "MIN_BLOCKS_FOR_ABSENCE",
    "Coverage",
    "Skill",
    "SkillRequest",
    "SkillResult",
]
