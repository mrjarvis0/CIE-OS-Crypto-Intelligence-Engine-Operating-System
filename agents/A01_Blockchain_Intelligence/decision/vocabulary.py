"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    decision.vocabulary

Purpose:
    Bind the words a conclusion may use to the confidence behind it.

Design goals:
    - One table, from evidence-standard.md §7, applied by every surface
    - Verb chosen from confidence, never supplied by a caller
    - Forbidden verbs detectable, so a violation can be caught in a test
    - Bands are closed intervals with no gaps and no overlap
    - Pure string policy; no I/O, no state

Notes:
    Natural language upgrades confidence silently. "Appears to have moved"
    and "moved" describe the same evidence and make different claims, and a
    reader takes the stronger one at face value. The mission's ethical
    principles require facts and inferences to stay distinguishable, so the
    verb is derived from the number rather than chosen alongside it.

    ``evidence-standard.md`` §7 assigns enforcement to
    ``intelligence/reporting/``. That was right when there was one renderer.
    There are now several -- the CLI, the REST API, any future dashboard -- and
    a rule enforced in each renderer is a rule enforced in none of them: the
    next surface added is the one that forgets. So the table lives here, at the
    point where a conclusion is *formed*, and every renderer reads the verb it
    was given rather than picking its own.

    §7.1 forbids averaging confidence away. A report combining a 0.95 fact and
    a 0.30 inference must not present 0.62, because the average hides that the
    conclusion rests on the weak link. :func:`binding_constraint` returns that
    weak link, and :class:`decision.conclusions.Conclusion` carries it instead
    of a mean.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Iterable, Sequence


@dataclass(frozen=True, slots=True)
class ConfidenceBand:
    """One row of the evidence standard's vocabulary table."""

    #: Inclusive lower bound. The upper bound is the next band's floor.
    floor: float
    label: str
    permitted: tuple[str, ...]
    forbidden: tuple[str, ...]

    @property
    def verb(self) -> str:
        """The qualifier a renderer should use for this band."""
        return self.permitted[0]


#: evidence-standard.md §7, verbatim. Ordered high to low so the first match
#: wins and the bands cannot overlap by construction.
BANDS: Final[tuple[ConfidenceBand, ...]] = (
    ConfidenceBand(
        floor=0.90,
        label="established",
        permitted=("is", "did", "transferred"),
        forbidden=(),
    ),
    ConfidenceBand(
        floor=0.70,
        label="strong",
        permitted=("almost certainly", "strongly indicates"),
        forbidden=("is", "confirmed"),
    ),
    ConfidenceBand(
        floor=0.50,
        label="moderate",
        permitted=("likely", "appears to"),
        forbidden=("shows", "proves", "is", "confirmed"),
    ),
    ConfidenceBand(
        floor=0.30,
        label="weak",
        permitted=("possibly", "consistent with"),
        forbidden=("likely", "indicates", "shows", "proves", "is", "confirmed"),
    ),
    ConfidenceBand(
        floor=0.0,
        label="insufficient",
        permitted=("cannot be determined", "insufficient evidence"),
        forbidden=(
            "possibly",
            "likely",
            "indicates",
            "shows",
            "proves",
            "is",
            "confirmed",
            "consistent with",
        ),
    ),
)


class VocabularyError(ValueError):
    """Raised when wording claims more than its confidence supports."""


def band_for(confidence: float) -> ConfidenceBand:
    """
    The band a confidence falls in.

    Values outside 0..1 are clamped rather than rejected. A confidence of 1.4
    is a bug upstream, but refusing to describe it would replace a wrong number
    with no output at all -- and the clamped band is the honest reading of what
    was meant.
    """
    value = max(0.0, min(1.0, float(confidence)))
    for band in BANDS:
        if value >= band.floor:
            return band
    return BANDS[-1]


def qualifier(confidence: float) -> str:
    """The verb a renderer must use at this confidence."""
    return band_for(confidence).verb


def permitted_verbs(confidence: float) -> tuple[str, ...]:
    return band_for(confidence).permitted


def violations(text: str, confidence: float) -> tuple[str, ...]:
    """
    Forbidden verbs present in ``text`` at this confidence.

    Word-boundary matching, so "is" does not fire inside "this" or "analysis".
    Returned rather than raised so a caller can log every violation in a
    rendered report at once instead of stopping at the first.
    """
    band = band_for(confidence)
    lowered = f" {text.lower()} "
    found = [
        verb
        for verb in band.forbidden
        if f" {verb} " in lowered or lowered.startswith(f" {verb} ")
    ]
    return tuple(found)


def enforce(text: str, confidence: float) -> str:
    """
    Return ``text`` unchanged, or raise if it overclaims.

    Used at the boundary where a rendered string is about to be published. A
    renderer emitting "is" for a 0.55-confidence claim launders an inference
    into a fact, which the mission's ethical principles prohibit outright --
    so this raises rather than rewriting. Silently softening the wording would
    hide a defect in whatever produced it.
    """
    found = violations(text, confidence)
    if found:
        band = band_for(confidence)
        raise VocabularyError(
            f"wording claims more than {confidence:.2f} supports: "
            f"{', '.join(found)} forbidden at {band.label!r}; "
            f"use one of {', '.join(band.permitted)}"
        )
    return text


@dataclass(frozen=True, slots=True)
class BindingConstraint:
    """
    The weakest link a conclusion rests on.

    Reported instead of an average, per §7.1. Averaging a 0.95 fact with a 0.30
    inference yields 0.62, which describes neither and hides that the whole
    conclusion fails if the inference does.
    """

    confidence: float
    source: str
    reason: str = ""

    @property
    def band(self) -> ConfidenceBand:
        return band_for(self.confidence)

    @property
    def qualifier(self) -> str:
        return self.band.verb

    def as_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "source": self.source,
            "band": self.band.label,
            "qualifier": self.qualifier,
            "reason": self.reason,
        }


def binding_constraint(
    items: Iterable[tuple[str, float]] | Sequence[tuple[str, float]],
    *,
    default_source: str = "no evidence",
) -> BindingConstraint:
    """
    The lowest-confidence contributor, which is what actually bounds a claim.

    A chain of reasoning is no stronger than its weakest step, so the minimum
    is the honest summary. An empty input yields zero confidence rather than a
    vacuous maximum: nothing supporting a claim is not the same as a claim
    needing no support.
    """
    entries = list(items)
    if not entries:
        return BindingConstraint(
            confidence=0.0,
            source=default_source,
            reason="no contributing evidence",
        )

    source, confidence = min(entries, key=lambda pair: pair[1])
    return BindingConstraint(
        confidence=max(0.0, min(1.0, float(confidence))),
        source=source,
        reason=f"weakest of {len(entries)} contributor(s)",
    )


__all__ = [
    "BANDS",
    "BindingConstraint",
    "ConfidenceBand",
    "VocabularyError",
    "band_for",
    "binding_constraint",
    "enforce",
    "permitted_verbs",
    "qualifier",
    "violations",
]
