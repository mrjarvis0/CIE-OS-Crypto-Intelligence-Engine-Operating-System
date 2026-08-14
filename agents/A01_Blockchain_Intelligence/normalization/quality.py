"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    normalization.quality

Purpose:
    Judge how complete and plausible a canonical record is, without rejecting
    it for being either.

Design goals:
    - Findings annotate; only validation rejects
    - Every finding names what is suspect and why it matters
    - Severity distinguishes "incomplete" from "implausible"
    - Deterministic: the same record always scores the same
    - No network, no storage lookups

Notes:
    Quality is separated from validation because they answer different
    questions and deserve different powers. Validation asks whether the payload
    is a coherent statement about the chain; if it is not, nothing can be built
    on it and it is refused. Quality asks how much the coherent statement is
    worth -- whether the transaction bodies came with it, whether the timestamp
    is plausible, whether it arrived from a corroborating source.

    Collapsing the two is a mistake in both directions. Rejecting on quality
    throws away usable data because it was merely thin: a block fetched without
    expanded transactions is perfectly good for tracking chain progress, and
    refusing it would stall ingestion over a preference. Ignoring quality is
    worse -- a thin record reaching a detector unlabelled is read as complete,
    and "no large transfers in this block" is then asserted from a record that
    never contained transfers at all.

    So findings travel with the record. A detector that needs expanded
    transactions can check for the completeness finding and decline, rather
    than concluding from an absence it created itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, Iterable

from schemas.block import CanonicalBlock
from sensors.envelope import CaptureGap

#: A chain timestamp this far ahead of local time is not plausible. Producers
#: have limited freedom to lie about the clock, and clients drift; this is loose
#: enough to absorb both and tight enough to catch a wrong-network payload.
MAX_FUTURE_DRIFT: Final[timedelta] = timedelta(minutes=15)

#: Before this, no EVM chain existed. A timestamp below it is not an old block,
#: it is a misread field.
MIN_PLAUSIBLE_TIMESTAMP: Final[datetime] = datetime(2015, 1, 1, tzinfo=UTC)

#: Checks whose incompleteness was chosen rather than suffered.
#:
#: A block below this line is missing transactions because a stated floor
#: dropped them, not because a fetch failed -- so the shortfall has a boundary,
#: and a consumer can tell which side of it a question falls on. Everything not
#: listed here is an unbounded loss: nothing is known about what is missing, so
#: nothing may be concluded from its absence.
#:
#: Deliberately narrow. A check is added here only when the record itself states
#: the limit of what was dropped; being wrong in this direction licenses a claim
#: the data cannot carry, which is the failure this whole module exists to
#: prevent. ``provenance`` is left out for that reason -- a block that cannot be
#: cited is a weaker record whatever else it contains.
BOUNDED_CHECKS: Final[frozenset[str]] = frozenset({"selective_capture"})


class Severity(StrEnum):
    """How much a finding should change what a consumer does."""

    #: The record is complete and plausible in this respect.
    OK = "ok"
    #: Usable, but narrower than it looks. A consumer must not infer absence.
    INCOMPLETE = "incomplete"
    #: Internally odd. Usable, but the source deserves suspicion.
    IMPLAUSIBLE = "implausible"


@dataclass(frozen=True, slots=True)
class QualityFinding:
    """One observation about a record's completeness or plausibility."""

    check: str
    severity: Severity
    message: str
    #: What a consumer must not conclude from this record. The field that makes
    #: a finding actionable rather than decorative.
    do_not_infer: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity.value,
            "message": self.message,
            "do_not_infer": self.do_not_infer,
        }


@dataclass(frozen=True, slots=True)
class QualityReport:
    """
    Every finding for one record, and whether any of them matter.

    ``complete`` and ``plausible`` are separate because they license different
    things. An incomplete record supports positive claims but not negative ones.
    An implausible record supports neither strongly, whatever it contains.
    """

    findings: tuple[QualityFinding, ...] = ()

    @property
    def complete(self) -> bool:
        return not any(f.severity is Severity.INCOMPLETE for f in self.findings)

    @property
    def plausible(self) -> bool:
        return not any(f.severity is Severity.IMPLAUSIBLE for f in self.findings)

    @property
    def clean(self) -> bool:
        return self.complete and self.plausible

    @property
    def incomplete_reason(self) -> str:
        """
        Which checks made this record incomplete, comma-separated; empty if none.

        The check names themselves, not a re-description of them. A second
        vocabulary for the same facts is a translation layer that drifts, and
        the names are already stable identifiers used in registries and logs.

        This is the field storage keeps. ``complete`` alone cannot distinguish a
        block whose logs were refused from one whose small transfers were
        dropped on purpose, and the two license opposite conclusions: the first
        supports no negative claim at all, the second supports one with a stated
        boundary. Without the reason, every incomplete block is read as the
        worse case forever.
        """
        return ",".join(f.check for f in self.findings if f.severity is Severity.INCOMPLETE)

    @property
    def bounded(self) -> bool:
        """
        Whether every shortfall in this record is one that states its own limit.

        False for a complete record -- there is nothing to bound -- so a caller
        asks ``complete or bounded``, and the two answer different questions.
        """
        incomplete = self.by_severity(Severity.INCOMPLETE)
        return bool(incomplete) and all(f.check in BOUNDED_CHECKS for f in incomplete)

    def by_severity(self, severity: Severity) -> tuple[QualityFinding, ...]:
        return tuple(f for f in self.findings if f.severity is severity)

    def as_dict(self) -> dict[str, Any]:
        return {
            "complete": self.complete,
            "plausible": self.plausible,
            "bounded": self.bounded,
            "incomplete_reason": self.incomplete_reason,
            "findings": [f.as_dict() for f in self.findings],
        }


def assess_block(
    block: CanonicalBlock,
    *,
    now: datetime | None = None,
    capture_gaps: Iterable[CaptureGap] = (),
    capture_floor: int | None = None,
) -> QualityReport:
    """
    Judge one canonical block.

    ``now`` is injectable so the plausibility window is testable without the
    test depending on when it runs.

    ``capture_gaps`` carries what the *capture* failed to obtain, which this
    function cannot see for itself. Everything else here is derivable from the
    block: a block that was fetched without transaction expansion says so in
    its own fields. Logs do not work that way -- they arrive as a separate
    record, so a block whose logs were refused is indistinguishable, by
    inspection, from a block that emitted none. The caller who made the request
    is the only party that knows, so it has to tell us.

    ``capture_floor`` says the missing transactions were dropped deliberately,
    below a materiality threshold, rather than lost. Same reason: the block
    cannot tell the two apart, and they mean opposite things.
    """
    reference = now or datetime.now(UTC)
    gaps = frozenset(capture_gaps)
    findings: list[QualityFinding] = []

    # Requested and refused. Without this the row reads as a block with no
    # token activity, and "no transfers here" gets asserted from a fetch that
    # never happened -- the exact failure this module's docstring describes.
    if CaptureGap.LOGS in gaps:
        findings.append(
            QualityFinding(
                check="logs_captured",
                severity=Severity.INCOMPLETE,
                message=(
                    "event logs were requested for this block and not obtained; "
                    "its token and NFT transfers are missing, not absent"
                ),
                do_not_infer="that no token transfers occurred in this block",
            )
        )

    # Selective capture is tested first, before either shortfall branch below.
    #
    # A block whose transactions were every one of them below the floor arrives
    # here with an empty transaction tuple -- identical, by inspection, to a
    # block fetched without expansion. Ordering this second reported "the block
    # was fetched without expansion" for a capture that fetched everything and
    # kept nothing, which sends a reader hunting a transport bug that does not
    # exist. The floor is the caller's own statement of intent, so when it is
    # present it is the explanation.
    if capture_floor is not None:
        kept = len(block.transactions)
        findings.append(
            QualityFinding(
                check="selective_capture",
                severity=Severity.INCOMPLETE,
                message=(
                    f"{kept} of {block.transaction_count} transactions kept; the "
                    f"rest were below the materiality floor of {capture_floor}"
                ),
                do_not_infer=(
                    f"that no transfer below {capture_floor} occurred in this "
                    "block; transfers at or above it were all captured"
                ),
            )
        )

    # Counted but not captured. The distinction a detector must not lose: a
    # block with 200 transactions and none stored is not a quiet block.
    elif block.transaction_count > 0 and not block.transactions_expanded:
        findings.append(
            QualityFinding(
                check="transactions_expanded",
                severity=Severity.INCOMPLETE,
                message=(
                    f"{block.transaction_count} transactions counted, none captured; "
                    "the block was fetched without expansion"
                ),
                do_not_infer="that no transfers occurred in this block",
            )
        )

    # Partially captured: some entries failed normalization. Worse than none,
    # because the shortfall is easy to miss.
    elif block.transactions_expanded and len(block.transactions) < block.transaction_count:
        missing = block.transaction_count - len(block.transactions)
        findings.append(
            QualityFinding(
                check="transactions_complete",
                severity=Severity.INCOMPLETE,
                message=(
                    f"{missing} of {block.transaction_count} transactions could not "
                    "be normalized"
                ),
                do_not_infer="that the stored transactions are the whole block",
            )
        )

    if block.timestamp > reference + MAX_FUTURE_DRIFT:
        findings.append(
            QualityFinding(
                check="timestamp_future",
                severity=Severity.IMPLAUSIBLE,
                message=f"block timestamp {block.timestamp.isoformat()} is in the future",
                do_not_infer="that this block's ordering by time is reliable",
            )
        )

    if block.timestamp < MIN_PLAUSIBLE_TIMESTAMP:
        findings.append(
            QualityFinding(
                check="timestamp_ancient",
                severity=Severity.IMPLAUSIBLE,
                message=(
                    f"block timestamp {block.timestamp.isoformat()} predates any "
                    "EVM chain; the field was probably misread"
                ),
                do_not_infer="that this block is genuinely old",
            )
        )

    # An empty block is normal. An empty block that also burned gas is not.
    if block.transaction_count == 0 and block.gas_used:
        findings.append(
            QualityFinding(
                check="gas_without_transactions",
                severity=Severity.IMPLAUSIBLE,
                message=f"no transactions but {block.gas_used} gas used",
                do_not_infer="that this block's transaction count is right",
            )
        )

    if not block.source_record_id:
        findings.append(
            QualityFinding(
                check="provenance",
                severity=Severity.INCOMPLETE,
                message="no source record id; the capture cannot be cited",
                do_not_infer="that this record can support an evidence chain",
            )
        )

    return QualityReport(findings=tuple(findings))


__all__ = [
    "BOUNDED_CHECKS",
    "MAX_FUTURE_DRIFT",
    "MIN_PLAUSIBLE_TIMESTAMP",
    "QualityFinding",
    "QualityReport",
    "Severity",
    "assess_block",
]
