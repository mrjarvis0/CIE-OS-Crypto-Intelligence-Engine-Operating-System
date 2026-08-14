"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.narrative.grounding

Purpose:
    Check that every particular a narrative states can be traced to evidence,
    and refuse to publish the ones that cannot.

Design goals:
    - Deterministic: no model judges whether a model hallucinated
    - Checks particulars, because that is what gets fabricated
    - Blocks publication rather than softening wording
    - Reports which span failed and what it could not be matched to
    - States its own limits; a check that oversells itself is worse than none

Notes:
    ``evidence-standard.md`` §6 is the contract: a model may structure,
    summarise and explain evidence, and may never introduce a factual claim
    absent from the evidence chain. Any such claim "is a hallucination by
    definition", and this module "must detect and strip it".

    **What is checked, and why that choice.** Deciding whether an arbitrary
    English sentence is a factual assertion is not something to attempt
    deterministically, and using a second model to judge the first only moves
    the trust problem. So the check targets **checkable particulars** — the
    addresses, transaction hashes, block heights, quantities and percentages a
    narrative names. In blockchain intelligence a damaging hallucination is
    almost always one of those: an address that never appeared, a figure nobody
    measured, a count that was invented to round out a sentence. Every
    particular must appear in the evidence; prose carrying none is the
    structuring and explanation the doctrine permits.

    **What is not checked, stated plainly.** This catches fabricated
    *particulars*, not fabricated *relations* between real ones. "0xabc sent
    500 ETH to 0xdef" and "0xdef sent 500 ETH to 0xabc" contain identical
    particulars and only one may be true. Detecting that needs the relation
    modelled as evidence rather than as prose, which is why
    :class:`NarrativeComposer` builds sentences from evidence fields instead of
    letting a model phrase them. The check is a backstop for the composer's
    guarantee, not a substitute for it.

    Numbers are matched by value, not by string. "1,000,000" and "1000000" are
    the same quantity, and a check that missed the comma would either reject
    correct prose or teach the caller to strip formatting until it passed.
"""

from __future__ import annotations

import logging
import re

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final, Iterable, Sequence

logger = logging.getLogger("a01.intelligence.narrative")

#: Abbreviated addresses, the form A01 itself renders: ``0x31a1…d07b``.
#: Matched before the full-hex pattern and checked at *both* ends. Checking
#: only the prefix would leave the suffix free to be fabricated, and the
#: suffix is the half a reader uses to tell two similar addresses apart.
_HEX_SHORT = re.compile(r"(0x[0-9a-fA-F]{2,})(?:\.{3}|[……])([0-9a-fA-F]{2,})")

#: Full hex addresses and hashes. Four digits rather than six, because
#: ``Address.short()`` emits ``0x`` plus four — a minimum above what A01
#: produces would leave its own output unchecked.
#: Case-insensitive: EIP-55 encodes a checksum in case, so a case-sensitive
#: match would reject a correctly checksummed address the evidence recorded
#: in lowercase.
_HEX = re.compile(r"0x[0-9a-fA-F]{4,}")

#: Numbers, including grouped and decimal forms. Bounded to avoid matching
#: inside a hex string, which is handled separately.
_NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.x])\d+(?:\.\d+)?")

#: Quantities small enough to be prose rather than data. "two of three
#: sources", "the top 5" — requiring evidence for these produces noise that
#: trains a caller to ignore the report.
SMALL_NUMBER_CEILING: Final[int] = 10

#: Tolerance for matching a narrative figure against an evidence figure.
#: Narratives round; evidence does not. Relative, so it holds across scales.
NUMERIC_TOLERANCE: Final[Decimal] = Decimal("0.005")


class Particular(StrEnum):
    """What kind of checkable thing was found."""

    HEX = "hex"
    QUANTITY = "quantity"


@dataclass(frozen=True, slots=True)
class Finding:
    """One particular in the narrative, and whether evidence backs it."""

    kind: Particular
    text: str
    grounded: bool
    #: The evidence artifact this matched, when it did.
    evidence_id: str = ""
    #: Character span in the narrative, so a caller can point at it.
    span: tuple[int, int] = (0, 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "text": self.text,
            "grounded": self.grounded,
            "evidence_id": self.evidence_id,
            "span": list(self.span),
        }


@dataclass(frozen=True, slots=True)
class GroundingReport:
    """
    The verdict on one narrative.

    ``publishable`` is the field that matters. False means the text states
    something the evidence does not, and the doctrine's answer to that is to
    block it rather than to qualify it — a hedged hallucination is still a
    hallucination.
    """

    narrative: str
    findings: tuple[Finding, ...] = ()
    #: Evidence ids the narrative successfully cited.
    cited: tuple[str, ...] = ()

    @property
    def ungrounded(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if not f.grounded)

    @property
    def publishable(self) -> bool:
        return not self.ungrounded

    @property
    def checked(self) -> int:
        return len(self.findings)

    def reason(self) -> str:
        """One line naming what blocked publication, or empty."""
        if self.publishable:
            return ""
        items = ", ".join(f.text for f in self.ungrounded[:5])
        more = "" if len(self.ungrounded) <= 5 else f" (+{len(self.ungrounded) - 5} more)"
        return f"not present in the evidence chain: {items}{more}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "publishable": self.publishable,
            "checked": self.checked,
            "ungrounded_count": len(self.ungrounded),
            "reason": self.reason(),
            "cited": list(self.cited),
            "findings": [f.as_dict() for f in self.findings],
        }


@dataclass
class _EvidenceIndex:
    """
    Every particular the evidence chain contains, flattened for lookup.

    Built once per check. The evidence is nested and heterogeneous, and
    searching it per particular would make the check quadratic in the size of
    a report.
    """

    hexes: dict[str, str] = field(default_factory=dict)
    numbers: list[tuple[Decimal, str]] = field(default_factory=list)

    def add(self, value: Any, evidence_id: str) -> None:
        """Index one value from an artifact, recursing into containers."""
        if isinstance(value, dict):
            for nested in value.values():
                self.add(nested, evidence_id)
            return
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                self.add(nested, evidence_id)
            return
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float, Decimal)):
            self.numbers.append((Decimal(str(value)), evidence_id))
            return
        if isinstance(value, str):
            for match in _HEX.finditer(value):
                self.hexes.setdefault(match.group(0).lower(), evidence_id)
            for match in _NUMBER.finditer(value):
                parsed = _to_decimal(match.group(0))
                if parsed is not None:
                    self.numbers.append((parsed, evidence_id))

    def find_hex(self, text: str) -> str | None:
        """
        Match a hex particular, allowing a prefix.

        Narratives shorten addresses because full ones are unreadable, so a
        prefix of a known address counts — the address still has to exist in
        the evidence.
        """
        lowered = text.lower()
        direct = self.hexes.get(lowered)
        if direct is not None:
            return direct
        for known, evidence_id in self.hexes.items():
            if known.startswith(lowered):
                return evidence_id
        return None

    def find_abbreviated(self, prefix: str, suffix: str) -> str | None:
        """
        Match ``0xabcd…wxyz`` against a known address, checking both ends.

        Both ends must belong to the *same* address. Checking them separately
        would let a real prefix and a real suffix from two different addresses
        combine into one that was never observed.
        """
        head = prefix.lower()
        tail = suffix.lower()
        for known, evidence_id in self.hexes.items():
            if known.startswith(head) and known.endswith(tail):
                return evidence_id
        return None

    def find_number(self, value: Decimal) -> str | None:
        """Match a quantity within tolerance, since narratives round."""
        for known, evidence_id in self.numbers:
            if _close(value, known):
                return evidence_id
        return None


def _to_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _close(left: Decimal, right: Decimal) -> bool:
    """Relative comparison, so tolerance holds at every scale."""
    if left == right:
        return True
    scale = max(abs(left), abs(right))
    if scale == 0:
        return False
    return abs(left - right) / scale <= NUMERIC_TOLERANCE


class GroundingCheck:
    """
    Verifies a narrative against the evidence it claims to describe.

    Deterministic by design: a model must not be the thing that decides whether
    a model hallucinated, because the failure mode is correlated — the same
    fluency that produces a convincing fabrication produces a convincing
    justification for it.
    """

    def __init__(self, *, small_number_ceiling: int = SMALL_NUMBER_CEILING) -> None:
        self._ceiling = small_number_ceiling

    def index(self, evidence: Iterable[Any]) -> _EvidenceIndex:
        """Flatten evidence artifacts into a lookup of their particulars."""
        index = _EvidenceIndex()
        for artifact in evidence:
            evidence_id = _identify(artifact)
            for value in _values_of(artifact):
                index.add(value, evidence_id)
        return index

    def check(self, narrative: str, evidence: Sequence[Any]) -> GroundingReport:
        """
        Find every checkable particular and try to ground it.

        Returns a report rather than raising: a caller usually wants to log the
        whole set of failures, and blocking is the caller's decision to make at
        the publication boundary via :meth:`publish`.
        """
        index = self.index(evidence)
        findings: list[Finding] = []
        cited: list[str] = []

        # Abbreviations first, and their spans are claimed so the full-hex pass
        # does not re-check the prefix on its own and report it grounded when
        # the suffix was not.
        abbreviated: list[tuple[int, int]] = []
        for match in _HEX_SHORT.finditer(narrative):
            evidence_id = index.find_abbreviated(match.group(1), match.group(2))
            findings.append(
                Finding(
                    kind=Particular.HEX,
                    text=match.group(0),
                    grounded=evidence_id is not None,
                    evidence_id=evidence_id or "",
                    span=match.span(),
                )
            )
            abbreviated.append(match.span())
            if evidence_id:
                cited.append(evidence_id)

        def already_checked(position: int) -> bool:
            return any(start <= position < end for start, end in abbreviated)

        for match in _HEX.finditer(narrative):
            if already_checked(match.start()):
                continue
            evidence_id = index.find_hex(match.group(0))
            findings.append(
                Finding(
                    kind=Particular.HEX,
                    text=match.group(0),
                    grounded=evidence_id is not None,
                    evidence_id=evidence_id or "",
                    span=match.span(),
                )
            )
            if evidence_id:
                cited.append(evidence_id)

        for match in _NUMBER.finditer(narrative):
            if _inside_hex(narrative, match.start()) or already_checked(match.start()):
                continue

            value = _to_decimal(match.group(0))
            if value is None:
                continue
            # Small counts are prose, not data. Demanding evidence for "two of
            # three sources" produces noise that trains a reader to skip the
            # report, which costs more than it catches.
            if abs(value) <= self._ceiling and value == value.to_integral_value():
                continue

            evidence_id = index.find_number(value)
            findings.append(
                Finding(
                    kind=Particular.QUANTITY,
                    text=match.group(0),
                    grounded=evidence_id is not None,
                    evidence_id=evidence_id or "",
                    span=match.span(),
                )
            )
            if evidence_id:
                cited.append(evidence_id)

        return GroundingReport(
            narrative=narrative,
            findings=tuple(findings),
            cited=tuple(dict.fromkeys(cited)),
        )

    def publish(self, narrative: str, evidence: Sequence[Any]) -> tuple[str, GroundingReport]:
        """
        Return the narrative only if every particular is grounded.

        An ungrounded narrative is replaced wholesale rather than edited. Redacting
        the offending spans would leave prose whose surrounding sentences still
        assert the removed facts, which reads as a complete report and is not one.
        """
        report = self.check(narrative, evidence)
        if report.publishable:
            return narrative, report

        logger.warning("narrative blocked by grounding check: %s", report.reason())
        return (
            "[withheld] This narrative asserted particulars absent from the "
            f"evidence chain and was not published. {report.reason()}"
        ), report

    def __repr__(self) -> str:
        return f"GroundingCheck(small_number_ceiling={self._ceiling})"


def _identify(artifact: Any) -> str:
    """The citable id of an artifact: its content hash, else its claim."""
    for attribute in ("content_hash", "claim"):
        value = getattr(artifact, attribute, None)
        if value:
            return str(value)
    if isinstance(artifact, dict):
        return str(artifact.get("content_hash") or artifact.get("claim") or "")
    return ""


def _values_of(artifact: Any) -> tuple[Any, ...]:
    """The fields of an artifact whose particulars count as evidence."""
    if isinstance(artifact, dict):
        return (
            artifact.get("claim"),
            artifact.get("data"),
            artifact.get("reference"),
            artifact.get("metadata"),
        )
    return (
        getattr(artifact, "claim", None),
        getattr(artifact, "data", None),
        getattr(artifact, "reference", None),
        getattr(artifact, "metadata", None),
    )


def _inside_hex(text: str, position: int) -> bool:
    """Whether a numeric match sits inside a hex literal already handled."""
    return any(m.start() <= position < m.end() for m in _HEX.finditer(text))


__all__ = [
    "NUMERIC_TOLERANCE",
    "SMALL_NUMBER_CEILING",
    "Finding",
    "GroundingCheck",
    "GroundingReport",
    "Particular",
]
