"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.narrative.composer

Purpose:
    Write the prose explanation of a decision, from the decision, without a
    model.

Design goals:
    - Grounded by construction: every particular comes from a field, not a phrase
    - Verbs taken from the decision, never chosen here
    - Absence stated only where coverage licenses it
    - Deterministic: same decision, same words
    - Always available; needs no key, no network, no model

Notes:
    The doctrine permits a model to "structure, summarise and explain" evidence.
    It is worth noticing how much of that a template does perfectly. A composed
    narrative cannot hallucinate a particular, because it never writes one it
    was not handed; it cannot overclaim, because it prints the qualifier the
    decision computed; and it cannot drift between runs, which makes it usable
    as a regression baseline.

    So this is the default narrator and the model is the option, rather than the
    other way round. That ordering matters beyond tidiness: a system whose only
    explanation path runs through a model has no output at all when the key is
    missing, the provider is down, or the response is blocked — and "no
    explanation" tends to become "publish it unchecked" under time pressure.

    The composer is also what makes :class:`GroundingCheck` a backstop rather
    than the primary defence. The check catches fabricated particulars; it
    cannot catch a fabricated *relation* between real ones. Building sentences
    from evidence fields means the relations are never phrased by a model in the
    first place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from decision.conclusions import Stance


@dataclass(frozen=True, slots=True)
class Narrative:
    """
    A composed explanation and the evidence it drew on.

    ``cites`` lists the artifacts the text refers to, so a reader can follow
    any statement back rather than being asked to trust the prose.
    """

    text: str
    cites: tuple[str, ...] = ()
    #: Producing method, recorded per evidence-standard.md §6. Deterministic
    #: composition is reproducible, and says so.
    method: str = "deterministic_composer@1"
    reproducibility: str = "deterministic"

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "cites": list(self.cites),
            "method": self.method,
            "reproducibility": self.reproducibility,
        }


class NarrativeComposer:
    """
    Turns a decision into prose.

    Holds no state and reads no data source. Everything it says comes from the
    decision it was given, which is what makes its output grounded without
    needing to be checked.
    """

    def compose(self, decision: Any, *, evidence: Sequence[Any] = ()) -> Narrative:
        """Write the explanation for one decision."""
        paragraphs: list[str] = [
            self._opening(decision),
            *self._findings(decision),
        ]

        coverage = self._coverage(decision)
        if coverage:
            paragraphs.append(coverage)

        alerts = self._alerts(decision)
        if alerts:
            paragraphs.append(alerts)

        steps = self._next_steps(decision)
        if steps:
            paragraphs.append(steps)

        paragraphs.append(
            "A01 provides evidence, not decisions; the determination remains "
            "with the operator."
        )

        cites = tuple(
            dict.fromkeys(
                ref
                for conclusion in getattr(decision, "conclusions", ())
                for ref in getattr(conclusion, "evidence_refs", ())
                if ref
            )
        )
        return Narrative(text="\n\n".join(p for p in paragraphs if p), cites=cites)

    # -- sections ---------------------------------------------------------

    def _opening(self, decision: Any) -> str:
        subject = getattr(decision, "subject", "the subject")
        actionable = getattr(decision, "actionable", ())
        undetermined = getattr(decision, "undetermined", ())

        if not actionable and not undetermined:
            return f"No analysis was produced for {subject}."
        if not actionable:
            return (
                f"For {subject}, nothing could be established from the evidence "
                f"available; {len(undetermined)} question(s) remain open."
            )
        return (
            f"For {subject}, {len(actionable)} finding(s) are supported by "
            f"evidence and {len(undetermined)} could not be determined."
        )

    def _findings(self, decision: Any) -> list[str]:
        """
        One paragraph per conclusion, in the decision's own words.

        The qualifier is printed, not chosen. Selecting a verb here would put
        the vocabulary rule in two places, and the renderer is the one that
        would drift.
        """
        lines: list[str] = []
        for conclusion in getattr(decision, "conclusions", ()):
            qualifier = getattr(conclusion, "qualifier", "cannot be determined")
            claim = getattr(conclusion, "claim", "")
            stance = getattr(conclusion, "stance", None)

            if stance is Stance.UNDETERMINED:
                sentence = f"It {qualifier} {claim.rstrip('.')}."
            else:
                sentence = f"The evidence {qualifier}: {claim.rstrip('.')}."

            confidence = getattr(conclusion, "confidence", 0.0)
            sentence += f" Confidence {confidence:.2f}."

            falsified_by = getattr(conclusion, "falsified_by", "")
            if falsified_by:
                sentence += f" This would be retracted by {falsified_by.rstrip('.')}."

            lines.append(sentence)
        return lines

    def _coverage(self, decision: Any) -> str:
        """
        State what the window does and does not license.

        Written even when coverage is good, because a reader cannot tell a
        report that checked its window from one that never looked.
        """
        constraint = getattr(decision, "constraint", None)
        supports_absence = any(
            getattr(c, "stance", None) is Stance.NEGATED
            for c in getattr(decision, "conclusions", ())
        )
        undetermined = getattr(decision, "undetermined", ())

        if undetermined and not supports_absence:
            return (
                "Negative findings are withheld: the stored history is not deep "
                "enough for an absence to mean anything, so questions that found "
                "nothing are reported as undetermined rather than as answered."
            )
        if constraint is not None and getattr(constraint, "confidence", 0.0) > 0:
            source = getattr(constraint, "source", "the weakest contributor")
            return (
                f"The binding constraint is {constraint.confidence:.2f} "
                f"({constraint.band.label}), set by {source}. That is the "
                "limit on the whole assessment, not an average of its parts."
            )
        return ""

    def _alerts(self, decision: Any) -> str:
        alerts = getattr(decision, "alerts", None)
        if alerts is None:
            return ""
        raised = getattr(alerts, "raised", ())
        if raised:
            return f"{len(raised)} alert(s) were raised."

        explanation = getattr(decision, "silence_explained", "")
        return f"No alert was raised: {explanation}." if explanation else ""

    def _next_steps(self, decision: Any) -> str:
        recommendations = list(getattr(decision, "recommendations", ()))[:3]
        if not recommendations:
            return ""
        steps = "; ".join(r.detail.rstrip(".") for r in recommendations)
        return f"To improve this assessment: {steps}."

    def __repr__(self) -> str:
        return "NarrativeComposer()"


__all__ = ["Narrative", "NarrativeComposer"]
