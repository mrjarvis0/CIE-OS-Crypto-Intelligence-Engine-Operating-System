"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    decision.recommendations

Purpose:
    Say what would make the next answer better — which observation to collect,
    which gap to close — and nothing about what anyone should buy or sell.

Design goals:
    - Investigative actions only; financial advice is out of scope, always
    - Each recommendation names the claim it would strengthen
    - Ordered by what unblocks the most
    - Derived from stated limitations, not invented
    - Deterministic for a given set of conclusions and caveats

Notes:
    ``identity/scope.md`` §4 excludes investment advice outright, and the CIE-OS
    operating rules require declining it rather than hedging it. The temptation
    in a system that has just detected a large exchange-bound transfer is
    obvious, and the boundary has to be structural rather than a matter of
    wording: this module can only emit actions from a fixed catalogue of
    *investigative* steps, so there is no path by which a market opinion reaches
    the output.

    What it does instead is close the loop between a weak answer and the reason
    it was weak. A01 already reports its limitations -- a shallow window, a
    missing balance sensor, an unmeasured error rate. A limitation nobody acts on
    is a complaint; the same limitation paired with the action that removes it is
    a work item. So each recommendation names the specific claim it would
    strengthen, and the ordering puts the one unblocking the most first.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable

from .conclusions import Conclusion, Stance


class Action(StrEnum):
    """The catalogue of things A01 may recommend. Investigative only."""

    #: Ingest more history, so absence claims become licensable.
    WIDEN_WINDOW = "widen_window"
    #: Backfill a gap, so counts stop being floors.
    FILL_GAP = "fill_gap"
    #: Run the backtest harness, so a detector can exceed 0.60 confidence.
    BACKTEST_DETECTOR = "backtest_detector"
    #: Add a data source the analysis needed and did not have.
    ADD_SOURCE = "add_source"
    #: Corroborate with an independent source before relying on the claim.
    CORROBORATE = "corroborate"
    #: Hand to a human analyst; the determination is not A01's to make.
    ESCALATE_TO_ANALYST = "escalate_to_analyst"


@dataclass(frozen=True, slots=True)
class Recommendation:
    """
    One suggested step, and what it would buy.

    ``unblocks`` names the claim that improves if the action is taken. A
    recommendation that cannot name one is a preference, and preferences do not
    belong in an intelligence product.
    """

    action: Action
    detail: str
    unblocks: str
    #: Rough ordering weight. Higher first.
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.unblocks.strip():
            raise ValueError(
                f"recommendation {self.action.value} must name what it unblocks"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "detail": self.detail,
            "unblocks": self.unblocks,
            "weight": self.weight,
        }


class RecommendationEngine:
    """
    Derives next steps from what the conclusions could not establish.

    Stateless. Every recommendation traces to a caveat or a stance already
    present in the conclusions, so the engine cannot introduce a claim of its
    own.
    """

    def recommend(
        self,
        conclusions: Iterable[Conclusion],
        *,
        coverage: dict[str, Any] | None = None,
    ) -> tuple[Recommendation, ...]:
        """Suggest what to do next, most useful first."""
        decided = list(conclusions)
        found: list[Recommendation] = []

        found.extend(self._from_coverage(coverage or {}, decided))
        found.extend(self._from_conclusions(decided))

        # Deduplicate by action and target, keeping the heaviest reason.
        best: dict[tuple[Action, str], Recommendation] = {}
        for item in found:
            key = (item.action, item.unblocks)
            if key not in best or item.weight > best[key].weight:
                best[key] = item

        return tuple(sorted(best.values(), key=lambda r: r.weight, reverse=True))

    # -- sources ----------------------------------------------------------

    def _from_coverage(
        self, coverage: dict[str, Any], conclusions: list[Conclusion]
    ) -> list[Recommendation]:
        """Recommendations that follow from how much history was stored."""
        if not coverage:
            return []

        found: list[Recommendation] = []
        window = coverage.get("window", {}) or {}

        if not coverage.get("supports_absence", False):
            blocks = coverage.get("blocks", 0)
            threshold = coverage.get("threshold", 0)
            found.append(
                Recommendation(
                    action=Action.WIDEN_WINDOW,
                    detail=(
                        f"backfill to at least {threshold} blocks; {blocks} stored. "
                        "Until then no negative finding can be stated."
                    ),
                    unblocks="every absence claim in this investigation",
                    weight=10.0,
                )
            )

        if window and not window.get("contiguous", True):
            found.append(
                Recommendation(
                    action=Action.FILL_GAP,
                    detail=(
                        f"stored heights {window.get('from_height')}–"
                        f"{window.get('to_height')} contain "
                        f"{window.get('span', 0) - window.get('blocks', 0)} missing "
                        "block(s); every count is a floor until they are filled"
                    ),
                    unblocks="transaction counts and volume totals",
                    weight=8.0,
                )
            )

        return found

    def _from_conclusions(
        self, conclusions: list[Conclusion]
    ) -> list[Recommendation]:
        """Recommendations that follow from what each conclusion could not do."""
        found: list[Recommendation] = []

        for conclusion in conclusions:
            for caveat in conclusion.caveats:
                lowered = caveat.lower()

                if "backtest" in lowered or "error rate" in lowered:
                    found.append(
                        Recommendation(
                            action=Action.BACKTEST_DETECTOR,
                            detail=(
                                f"run evaluation/ against a labelled window for "
                                f"{conclusion.detector}; its confidence is capped "
                                "until the error rate is measured"
                            ),
                            unblocks=f"{conclusion.detector} confidence above 0.60",
                            weight=9.0,
                        )
                    )

                if "balance" in lowered:
                    found.append(
                        Recommendation(
                            action=Action.ADD_SOURCE,
                            detail=(
                                "add a balance sensor; materiality cannot be "
                                "assessed from transfer history alone"
                            ),
                            unblocks="dormant reactivation materiality",
                            weight=6.0,
                        )
                    )

                # Split, because the two stopped being one problem. Address
                # labels are now loadable and loaded; a single recommendation
                # naming both would keep asking for a source that is already
                # there, and an operator who acts on it finds nothing to do.
                if "price" in lowered:
                    found.append(
                        Recommendation(
                            action=Action.ADD_SOURCE,
                            detail=(
                                "add a price feed; without one a USD floor "
                                "cannot be applied to a transfer"
                            ),
                            unblocks="whale USD thresholds",
                            weight=5.0,
                        )
                    )

                if "label" in lowered:
                    found.append(
                        Recommendation(
                            action=Action.ADD_SOURCE,
                            detail=(
                                "load address labels (a01 labels --load) and "
                                "read them where a counterparty's type is "
                                "needed; an unlabelled counterparty cannot be "
                                "told from an exchange deposit address"
                            ),
                            unblocks="counterparty type on transfer evidence",
                            weight=5.0,
                        )
                    )

            if conclusion.stance is Stance.AFFIRMED:
                found.append(
                    Recommendation(
                        action=Action.ESCALATE_TO_ANALYST,
                        detail=(
                            f"{conclusion.claim} at {conclusion.confidence:.2f} "
                            "confidence — A01 provides evidence, and the "
                            "determination belongs to a human analyst"
                        ),
                        unblocks=conclusion.claim,
                        weight=4.0,
                    )
                )
                found.append(
                    Recommendation(
                        action=Action.CORROBORATE,
                        detail=(
                            "confirm against an independent source before relying "
                            f"on this; retracted by: {conclusion.falsified_by}"
                        ),
                        unblocks=conclusion.claim,
                        weight=3.0,
                    )
                )

        return found

    def __repr__(self) -> str:
        return "RecommendationEngine()"


__all__ = ["Action", "Recommendation", "RecommendationEngine"]
