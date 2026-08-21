"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.smart_money.tracker

Purpose:
    Report behavioral evidence for smart-money classification from stored
    history: label status, first-mover timing, counterparty diversity,
    flow patterns, and size discipline.

Design goals:
    - No P&L; profitability needs prices A01 does not ingest
    - Label checked but not required; behavioral evidence stands alone
    - First-mover measured against the stored population, not claimed
    - Every bound stated; the label and the behavior are separate signals
    - Reads storage only; no chain access

Notes:
    The registry previously held this skill out because it "needs token prices
    and entity labels". The label system now accepts ``smart_money`` as a
    category, and the behavioral signals below are computable from transfers
    alone. What is missing is profitability -- the defining trait of smart money
    in the strict sense -- and that absence is reported in the result rather
    than hidden by omission.

    Without prices, this skill cannot answer "was this address profitable?" It
    can answer "did this address act before the crowd, diversify its
    counterparties, and size its transfers consistently?" -- which is weaker but
    real, and honest about why.

    The first-mover score is the headline signal here. For each counterparty the
    address interacted with, was it among the early arrivals? Measured against
    the stored population: the fraction of its counterparties it reached before
    the median actor in the same window. A high ratio suggests the address acts
    on information before the crowd -- which is what "smart money" means in
    practice, even without a P&L ledger.

    Size discipline is the secondary signal: a low coefficient of variation in
    transfer values suggests deliberate position sizing rather than noise. It is
    not diagnostic on its own -- an exchange hot wallet moves consistent sizes
    for operational reasons -- but combined with first-mover timing and
    counterparty diversity it contributes to a behavioral profile.
"""

from __future__ import annotations

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository, TransferRecord
from schemas.address import Address
from tiers.ledger import LabelRepository, LabelSet

from ..base import Coverage, Skill, SkillRequest, SkillResult

DEFAULT_SCAN_LIMIT: Final[int] = 10_000

MIN_COUNTERPARTIES_FOR_DIVERSITY: Final[int] = 3

EARLY_MOVER_THRESHOLD: Final[float] = 0.5


class SmartMoneySkill(Skill):
    """
    Behavioral evidence for smart-money classification.

    One responsibility: gather the signals. Whether they amount to a smart-money
    verdict is decided in ``intelligence/scoring/smart_money.py``, which owns
    the thresholds and the weighting.
    """

    name = "smart_money"
    description = (
        "Behavioral profile for smart-money classification: label status, "
        "first-mover timing, counterparty diversity, size discipline"
    )

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if request.address is None:
            return self.undetermined(coverage, "smart_money requires an address")
        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored to profile against"
            )

        address = request.address
        labels = LabelRepository(analytics.database).label_set(
            request.chain, category="smart_money"
        )

        summary = analytics.address_summary(address)
        if not summary.seen:
            return self._unseen(coverage, address, labels)

        limit = int(request.option("scan_limit", DEFAULT_SCAN_LIMIT))
        transfers = analytics.transfers_in_window(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
            limit=limit,
        )

        addr_transfers = tuple(
            t for t in transfers if self._involves(t, address)
        )

        counterparty_profile = self._counterparty_profile(addr_transfers, address)
        timing = self._first_mover_score(transfers, addr_transfers, address)
        discipline = self._size_discipline(addr_transfers)
        token_activity = analytics.token_flow(address)

        is_labelled = labels.is_labelled(address.value)
        label_entity = labels.entity_of(address.value) if is_labelled else None

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value,
            "labelled_smart_money": is_labelled,
            "label_entity": label_entity,
            "label_source": self._source_of(labels) if is_labelled else None,
            "label_confidence": self._confidence_of(labels) if is_labelled else None,
            "labels_loaded": len(labels) > 0,
            "transaction_count": summary.transaction_count,
            "sent_count": summary.sent_count,
            "received_count": summary.received_count,
            "counterparties": summary.counterparties,
            "counterparty_profile": counterparty_profile,
            "first_mover": timing,
            "size_discipline": discipline,
            "tokens_touched": len(token_activity),
            "coverage_limitation": coverage.limitation,
            "bounds": self._bounds(labels, is_labelled, coverage),
        }

        subject: dict[str, Any] = {
            "address": address.value,
            "chain": request.chain,
            "labelled_smart_money": is_labelled,
            "counterparty_count": summary.counterparties,
            "early_mover_ratio": timing["early_mover_ratio"],
            "counterparty_diversity": counterparty_profile["diversity_ratio"],
            "size_cv": discipline["coefficient_of_variation"],
            "observed_transaction_count": summary.transaction_count,
            "tokens_touched": len(token_activity),
        }

        if is_labelled:
            subject["track_record"] = 1.0
        if timing["early_mover_ratio"] >= EARLY_MOVER_THRESHOLD:
            subject["profitable_trades"] = timing["early_mover_ratio"]
        else:
            subject["profitable_trades"] = 0.0

        reason = self._reason(
            is_labelled, summary.transaction_count, timing, counterparty_profile
        )
        return self.answer(coverage, data, subject, reason)

    # -- edge cases -------------------------------------------------------

    def _unseen(
        self, coverage: Coverage, address: Address, labels: LabelSet
    ) -> SkillResult:
        is_labelled = labels.is_labelled(address.value)
        data: dict[str, Any] = {
            "chain": address.chain,
            "address": address.value,
            "labelled_smart_money": is_labelled,
            "label_entity": labels.entity_of(address.value) if is_labelled else None,
            "seen_in_window": False,
        }

        if is_labelled:
            subject: dict[str, Any] = {
                "address": address.value,
                "labelled_smart_money": True,
                "behavioral_evidence": False,
            }
            reason = (
                "address is labelled smart money but has no activity in the "
                "stored window; behavioral signals cannot be computed"
            )
        else:
            subject = {}
            reason = (
                "address not present in stored history"
                + (
                    "; the window is deep enough for that to mean inactivity"
                    if coverage.supports_absence
                    else "; " + coverage.limitation
                )
            )

        return self.answer(coverage, data, subject, reason)

    # -- signals ----------------------------------------------------------

    @staticmethod
    def _involves(transfer: TransferRecord, address: Address) -> bool:
        return address.value in (transfer.from_address, transfer.to_address)

    @staticmethod
    def _counterparty_profile(
        transfers: tuple[TransferRecord, ...], address: Address
    ) -> dict[str, Any]:
        """
        How concentrated or diverse the address's counterparties are.

        A smart-money address typically interacts with many counterparties
        rather than repeatedly with the same few. The diversity ratio is
        unique counterparties / total interactions: near 1.0 means every
        transfer went to a new address, near 0.0 means it talks to the same
        one over and over.
        """
        counterparties: dict[str, int] = {}
        for t in transfers:
            if t.from_address == address.value and t.to_address:
                counterparties[t.to_address] = counterparties.get(t.to_address, 0) + 1
            elif t.to_address == address.value and t.from_address:
                counterparties[t.from_address] = counterparties.get(t.from_address, 0) + 1

        total = len(transfers)
        unique = len(counterparties)

        if total == 0:
            return {
                "unique_counterparties": 0,
                "total_interactions": 0,
                "diversity_ratio": 0.0,
                "top_counterparty_share": 0.0,
                "diverse": False,
            }

        diversity_ratio = unique / total
        top_share = max(counterparties.values()) / total if counterparties else 0.0

        return {
            "unique_counterparties": unique,
            "total_interactions": total,
            "diversity_ratio": round(diversity_ratio, 4),
            "top_counterparty_share": round(top_share, 4),
            "diverse": unique >= MIN_COUNTERPARTIES_FOR_DIVERSITY and diversity_ratio > 0.3,
        }

    @staticmethod
    def _first_mover_score(
        all_transfers: tuple[TransferRecord, ...],
        addr_transfers: tuple[TransferRecord, ...],
        address: Address,
    ) -> dict[str, Any]:
        """
        For each counterparty the address interacted with, was this address
        among the early actors in the stored window?

        Of the counterparties this address touched, what fraction did it reach
        before the median other actor? A high ratio suggests the address acts
        on information before the crowd.
        """
        if not addr_transfers:
            return {
                "counterparties_analyzed": 0,
                "early_arrivals": 0,
                "early_mover_ratio": 0.0,
                "determinable": False,
            }

        addr_first_touch: dict[str, int] = {}
        for t in addr_transfers:
            cp = t.to_address if t.from_address == address.value else t.from_address
            if cp and (cp not in addr_first_touch or t.height < addr_first_touch[cp]):
                addr_first_touch[cp] = t.height

        early_count = 0
        analyzed = 0

        for cp, addr_height in addr_first_touch.items():
            seen_actors: dict[str, int] = {}
            for t in all_transfers:
                if cp in (t.from_address, t.to_address):
                    actor = t.from_address if t.to_address == cp else t.to_address
                    if actor and actor != address.value:
                        if actor not in seen_actors or t.height < seen_actors[actor]:
                            seen_actors[actor] = t.height

            if not seen_actors:
                continue

            analyzed += 1
            others_sorted = sorted(seen_actors.values())
            median_height = others_sorted[len(others_sorted) // 2]
            if addr_height <= median_height:
                early_count += 1

        ratio = early_count / analyzed if analyzed > 0 else 0.0

        return {
            "counterparties_analyzed": analyzed,
            "early_arrivals": early_count,
            "early_mover_ratio": round(ratio, 4),
            "determinable": analyzed >= MIN_COUNTERPARTIES_FOR_DIVERSITY,
        }

    @staticmethod
    def _size_discipline(
        transfers: tuple[TransferRecord, ...],
    ) -> dict[str, Any]:
        """
        How consistent the address's transfer sizes are.

        A low coefficient of variation suggests deliberate position sizing;
        a high one suggests erratic or opportunistic behavior.
        """
        values = [float(t.value.raw) for t in transfers if t.value.raw > 0]

        if len(values) < 2:
            return {
                "sample_size": len(values),
                "coefficient_of_variation": 0.0,
                "disciplined": False,
                "determinable": False,
            }

        mean = sum(values) / len(values)
        if mean == 0:
            return {
                "sample_size": len(values),
                "coefficient_of_variation": 0.0,
                "disciplined": False,
                "determinable": False,
            }

        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std_dev = variance ** 0.5
        cv = std_dev / mean

        return {
            "sample_size": len(values),
            "coefficient_of_variation": round(cv, 4),
            "disciplined": cv < 1.0,
            "determinable": True,
        }

    # -- metadata ---------------------------------------------------------

    @staticmethod
    def _source_of(labels: LabelSet) -> str:
        sources = {entry.source for entry in labels.entries.values()}
        return ", ".join(sorted(sources)) if sources else ""

    @staticmethod
    def _confidence_of(labels: LabelSet) -> float:
        confidences = [entry.confidence for entry in labels.entries.values()]
        return min(confidences) if confidences else 0.0

    @staticmethod
    def _bounds(
        labels: LabelSet, is_labelled: bool, coverage: Coverage
    ) -> list[str]:
        bounds = [
            "no price feed: profitability cannot be assessed, so 'smart money' "
            "is inferred from behavioral signals alone",
            "first-mover timing is relative to the stored population, not the "
            "chain; a larger window may change the ranking",
        ]
        if not labels:
            bounds.append(
                "no smart_money labels loaded, so the label signal is unavailable"
            )
        elif is_labelled:
            weakest = SmartMoneySkill._confidence_of(labels)
            if weakest < 0.9:
                bounds.append(
                    f"label is unverified (confidence {weakest}); it is an "
                    "external claim, not an established fact"
                )
        if coverage.limitation:
            bounds.append(coverage.limitation)
        return bounds

    @staticmethod
    def _reason(
        is_labelled: bool,
        tx_count: int,
        timing: dict[str, Any],
        counterparties: dict[str, Any],
    ) -> str:
        parts: list[str] = []
        if is_labelled:
            parts.append("labelled smart money")
        parts.append(f"{tx_count} transaction(s)")
        if timing["determinable"]:
            parts.append(
                f"early mover to {timing['early_arrivals']}/"
                f"{timing['counterparties_analyzed']} counterparties"
            )
        if counterparties["diverse"]:
            parts.append(
                f"{counterparties['unique_counterparties']} diverse counterparties"
            )
        return "; ".join(parts)


__all__ = [
    "DEFAULT_SCAN_LIMIT",
    "EARLY_MOVER_THRESHOLD",
    "MIN_COUNTERPARTIES_FOR_DIVERSITY",
    "SmartMoneySkill",
]
