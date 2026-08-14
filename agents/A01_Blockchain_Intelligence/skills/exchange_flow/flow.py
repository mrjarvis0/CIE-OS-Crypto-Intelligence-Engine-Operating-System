"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.exchange_flow.flow

Purpose:
    Answer what moved into and out of labelled exchange addresses over the
    stored window, per operator, with the bound that answer carries.

Design goals:
    - Direction from labels, never from behaviour
    - Deposits, withdrawals and internal movement reported separately
    - A zero answer licensed by coverage, or withheld
    - The label source named in the result, because the answer inherits it
    - Reads storage only; no chain access, no interpretation

Notes:
    This is the first skill whose answer depends on data A01 cannot observe. A
    transfer's direction is a fact about the chain; that the recipient is
    Binance is somebody's claim about an address. So the result carries the
    label source and its confidence, and a conclusion drawn from it is bounded
    by the weaker of the two.

    **The negative claim is where this gets interesting.** "No deposits to a
    labelled exchange in this window" is an absence, and absence needs coverage
    -- but selective capture means most windows can only support the *bounded*
    form: nothing at or above the floor arrived. That is still the answer to
    most questions anyone asks, so this skill consults
    :attr:`~skills.base.Coverage.supports_absence_above` and states the floor,
    rather than either asserting a clean zero or refusing to speak. It is the
    first consumer of the bounded gate, and the reason the gate was built.

    **What this cannot see** is stated rather than implied. Native value only:
    the stablecoin flows that dominate real exchange traffic are ERC-20
    transfers, and A01 stores those separately without label attribution. An
    address the list does not name is invisible, and no exchange list is
    complete. Both bound every figure here, and both are reported.
"""

from __future__ import annotations

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository
from pipeline.flows import FlowStats, roll_up, totals_by_entity
from schemas.amount import Amount
from tiers.ledger import LabelRepository
from tiers.warm import ExchangeFlowHour

from ..base import Skill, SkillRequest, SkillResult

#: Transfers scanned for one answer. Flow is a question about ordinary-sized
#: movement, so this cannot rank by value and take the top slice; it takes a
#: window in chain order and reports when the window bound it.
DEFAULT_SCAN_LIMIT: Final[int] = 50_000

#: Operators reported in the result body. The full set stays in the subject.
DEFAULT_ENTITY_LIMIT: Final[int] = 10


class ExchangeFlowSkill(Skill):
    """
    Deposits to and withdrawals from labelled exchange addresses.

    One responsibility: attribute stored transfers to operators and total them.
    Whether an inflow is sell pressure, accumulation, or a custody migration is
    not decided here -- and is not decidable from flow alone, which is why the
    result says direction and never intent.
    """

    name = "exchange_flow"
    description = (
        "Native value deposited to and withdrawn from labelled exchange addresses"
    )

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        labels = LabelRepository(analytics.database).label_set(
            request.chain, category="exchange"
        )
        if not labels:
            # Not an empty answer: the question cannot be asked at all. An
            # exchange-flow figure of zero with no labels loaded would be a
            # confident statement about a rule that never ran.
            return self.undetermined(
                coverage,
                "no exchange address labels loaded, so no transfer can be "
                "attributed to an exchange",
            )

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored to attribute"
            )

        limit = int(request.option("scan_limit", DEFAULT_SCAN_LIMIT))
        transfers, capped = analytics.transfers_by_height(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
            limit=limit,
        )
        quality = analytics.hourly_block_quality(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
        )

        stats = FlowStats()
        source = self._source_of(labels)
        hours = roll_up(
            request.chain,
            transfers,
            labels,
            quality=quality,
            label_source=source,
            stats=stats,
        )

        entities = totals_by_entity(hours)
        # From the per-transfer counters, never from the hourly rows. A transfer
        # between two exchanges is recorded on both of their hours -- correctly,
        # it is a fact about each -- so summing the rows would report one
        # rebalance as two.
        totals = stats.totals()
        floor = self._floor_of(hours)

        data: dict[str, Any] = {
            "chain": request.chain,
            "labelled_addresses": len(labels),
            "labelled_entities": len(labels.entities()),
            "label_source": source,
            # The weakest label in the set, not the best. Which label an
            # attribution rested on is not recorded per transfer, so anything
            # drawn from this answer could be resting on that one, and a
            # ceiling taken from the strongest would be a ceiling nothing
            # guarantees.
            "label_confidence": self._confidence_of(labels),
            "transfers_scanned": stats.seen,
            "attributed": stats.attributed,
            "hours": len(hours),
            "totals": totals,
            "entities": dict(list(entities.items())[:DEFAULT_ENTITY_LIMIT]),
            "filter": stats.as_dict(),
            "coverage_limitation": coverage.limitation,
            "bounds": self._bounds(labels, capped, stats, floor),
        }

        # The negative claim, and the only place this skill makes one. A window
        # that cannot license it reports the absence as undetermined rather than
        # as zero -- "no exchange deposits" from a four-block window is a
        # statement about storage wearing the clothes of a statement about the
        # chain.
        if stats.attributed == 0:
            licensed = (
                coverage.supports_absence_above(floor)
                if floor is not None
                else coverage.supports_absence
            )
            data["absence_licensed"] = licensed
            data["absence_floor"] = str(floor.raw) if floor is not None else None
            reason = (
                "no transfer in the stored window touched a labelled exchange "
                "address"
                if licensed
                else "no attributed flow found, and the window cannot license "
                "an absence"
            )
            subject: dict[str, Any] = {"exchange_flow": data} if licensed else {}
            return SkillResult(
                skill=self.name,
                determined=licensed,
                coverage=coverage,
                data=data,
                subject=subject,
                reason=reason,
            )

        subject = {
            "exchange_flow": data,
            "exchange_flow_hours": [hour.as_dict() for hour in hours],
        }
        reason = (
            f"{stats.attributed} transfer(s) attributed to "
            f"{len(entities)} exchange(s) across {len(hours)} hour(s)"
        )
        return self.answer(coverage, data, subject, reason)

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _floor_of(hours: tuple[ExchangeFlowHour, ...]) -> Amount | None:
        """The highest capture floor in the window; it bounds every claim from it."""
        floors = [hour.capture_floor for hour in hours if hour.capture_floor is not None]
        return max(floors, key=lambda floor: floor.raw) if floors else None

    @staticmethod
    def _confidence_of(labels: Any) -> float:
        """The lowest confidence in the label set; it bounds anything read off it."""
        confidences = [entry.confidence for entry in labels.entries.values()]
        return min(confidences) if confidences else 0.0

    @staticmethod
    def _source_of(labels: Any) -> str:
        sources = {entry.source for entry in labels.entries.values()}
        return ", ".join(sorted(sources)) if sources else ""

    @staticmethod
    def _bounds(
        labels: Any, capped: bool, stats: FlowStats, floor: Amount | None
    ) -> list[str]:
        """
        Everything that makes these figures narrower than they look.

        Listed rather than summarised: each of these bounds a different
        question, and a reader needs to know which one applies to theirs.
        """
        bounds = [
            "native value only; token and stablecoin transfers are not attributed",
            f"only addresses in the loaded list are visible ({len(labels)} across "
            f"{len(labels.entities())} operator(s)); no exchange list is complete",
        ]
        # The weakest label in the set, matching `label_confidence`. Reporting
        # the strongest would describe a label the answer may not rest on: which
        # one an attribution used is not recorded per transfer, so the floor is
        # the only figure that holds for all of them.
        weakest = ExchangeFlowSkill._confidence_of(labels)
        if labels and weakest < 0.9:
            bounds.append(
                f"labels are unverified (confidence {weakest}), so an "
                "attribution is an external claim rather than an established fact"
            )
        if capped:
            bounds.append(
                "the transfer scan hit its row cap, so every total here is a floor"
            )
        if stats.undated:
            bounds.append(
                f"{stats.undated} transfer(s) had no block timestamp and are "
                "excluded rather than placed in the nearest hour"
            )
        if floor is not None and floor.raw:
            bounds.append(
                f"blocks were captured selectively at a floor of {floor.raw}; "
                "transfers below it were never stored"
            )
        return bounds


__all__ = ["DEFAULT_ENTITY_LIMIT", "DEFAULT_SCAN_LIMIT", "ExchangeFlowSkill"]
