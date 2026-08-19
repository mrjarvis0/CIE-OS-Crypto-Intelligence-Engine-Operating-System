"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.whale_detection.transfers

Purpose:
    Assemble the large-transfer evidence the whale detector needs: the
    transfers themselves, and the population that makes "large" mean something.

Design goals:
    - Population supplied from stored history, so thresholds stay relative
    - Direction reported from the address's own point of view
    - Population size stated, so a thin population is visible
    - No verdict; qualification is DET-WHALE-01's decision

Notes:
    This skill exists because DET-WHALE-01 refuses to use an absolute
    threshold, and a relative threshold needs a population. The detector cannot
    fetch one -- it must not touch data -- so the population arrives in its
    subject, and building it correctly is this skill's whole job.

    Population quality decides whether the detector's percentile means anything,
    and it does so more sharply than it first appears. The detector ranks by the
    count of strictly-smaller observations, so the largest value in a population
    of ``n`` scores ``(n - 1) / n * 100``. Below :data:`MIN_POPULATION` the 99.9
    threshold is not merely noisy — it is **unreachable**, and every subject on
    the chain reports no whale activity while the thresholds, the population and
    the transfers all look correct. :func:`min_population_for` derives the bound
    from the threshold rather than guessing a round number, and a population
    below it is flagged rather than used.

    Zero-value transactions are excluded upstream in
    :meth:`SqliteAnalyticsRepository.transfer_values`. Contract calls that move
    nothing are most of chain traffic, and leaving them in the population drags
    every percentile down until a routine transfer clears the 99.9th.

    Direction is computed per address, not stored. The same transfer is an
    outflow for the sender and an inflow for the recipient, so it has no
    intrinsic direction -- only a direction relative to whoever is being asked
    about.
"""

from __future__ import annotations

import math

from typing import Any, Final

from database.analytics import SqliteAnalyticsRepository, TransferRecord
from config.constants import WHALE_PERCENTILE as DEFAULT_PERCENTILE
from schemas.address import Address
from tiers.ledger import LabelSet, LabelRepository

from ..base import Skill, SkillRequest, SkillResult

#: Transfers returned for the subject, largest first. The detector only needs
#: the candidates that could qualify, and a larger slice costs subject size for
#: no additional signal.
DEFAULT_TRANSFER_LIMIT: Final[int] = 100

def min_population_for(percentile: float) -> int:
    """
    Smallest population in which ``percentile`` is reachable at all.

    The detector ranks a transfer by the count of strictly-smaller observations
    (``intelligence.analysis.whale._percentile``), so the largest value in a
    population of ``n`` scores ``(n - 1) / n * 100`` and no higher. For the
    default 99.9 threshold that needs ``n >= 1000``.

    This is worth computing rather than guessing, because getting it wrong
    fails silently and in the worst direction. A population of 200 caps every
    rank at 99.5, so *no transfer can ever qualify* — the detector reports "no
    whale activity" for every subject on the chain, with a full population, a
    correct threshold, and nothing anywhere indicating that the test was
    unpassable.
    """
    if not 0.0 < percentile < 100.0:
        raise ValueError(f"percentile must be within (0, 100): {percentile}")
    return math.ceil(100.0 / (100.0 - percentile))


#: Population needed for the detector's default 99.9th-percentile threshold.
MIN_POPULATION: Final[int] = min_population_for(DEFAULT_PERCENTILE)


class WhaleTransferSkill(Skill):
    """
    Supplies large transfers and their population from stored history.

    One responsibility: gather and describe. Whether any transfer qualifies as
    whale-scale is decided by ``intelligence.analysis.whale``, which owns the
    thresholds and the false-positive suppression.
    """

    name = "whale_transfers"
    description = "Large transfers plus the value population that makes 'large' relative"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored to measure against"
            )

        limit = int(request.option("transfer_limit", DEFAULT_TRANSFER_LIMIT))
        population = analytics.transfer_values(request.chain)

        transfers = analytics.transfers_in_window(
            request.chain,
            from_height=request.from_height,
            to_height=request.to_height,
            limit=limit,
        )

        address = request.address
        if address is not None:
            transfers = tuple(
                t for t in transfers if self._involves(t, address)
            )

        # Loaded once per run, not per transfer. The set is a dict in memory and
        # the alternative is a query per counterparty, which on a 100-transfer
        # subject is 100 round trips to answer a question already in hand.
        labels = LabelRepository(analytics.database).label_set(
            request.chain, category="exchange"
        )

        entries = [self._entry(t, address, labels) for t in transfers]
        population_usable = len(population) >= MIN_POPULATION

        data: dict[str, Any] = {
            "chain": request.chain,
            "address": address.value if address else None,
            "labelled_addresses": len(labels),
            "transfer_count": len(entries),
            "population_size": len(population),
            "population_usable": population_usable,
            "largest_value": entries[0]["value"] if entries else None,
            "transfers": entries[:10],
            "coverage_limitation": coverage.limitation,
        }

        if not population_usable:
            data["population_note"] = (
                f"{len(population)} transfers in the population; the detector's "
                f"{DEFAULT_PERCENTILE} percentile threshold is unreachable below "
                f"{MIN_POPULATION}, so no transfer can qualify by percentile"
            )

        subject: dict[str, Any] = {
            "large_transfers": entries,
            # Passed even when thin: the detector reports `determinable` from
            # it, and withholding it would make a thin population look like no
            # population, which is a different problem.
            "transfer_population": [float(value) for value in population],
        }
        if address is not None:
            subject["address"] = address.value

        reason = f"{len(entries)} transfer(s) from a population of {len(population)}"
        return self.answer(coverage, data, subject, reason)

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _involves(transfer: TransferRecord, address: Address) -> bool:
        return address.value in (transfer.from_address, transfer.to_address)

    @staticmethod
    def _entry(
        transfer: TransferRecord, address: Address | None, labels: LabelSet
    ) -> dict[str, Any]:
        """
        One transfer in the shape the whale detector consumes.

        ``kind`` is always ``transfer``. The detector suppresses non-economic
        kinds -- internal rebalancing, bridge lock/mint, wrapping -- but
        recognising those needs contract labels and event decoding that A01
        does not yet have. Claiming a kind that has not been established would
        suppress real transfers or admit fake ones, so the honest value is the
        unclassified one.

        ``counterparty_type`` now answers from the label ledger, and its three
        values are three different statements. ``exchange`` is somebody's
        sourced claim about the address. ``unlabelled`` says the list was
        consulted and does not name it -- true, and not the same as saying it
        is not an exchange, because no list is complete. ``unknown`` says no
        list was consulted at all, which is what the detector needs in order to
        report exchange exposure as undetermined rather than as absent.
        """
        direction = "unknown"
        counterparty = None
        if address is not None:
            if transfer.from_address == address.value:
                direction = "out"
                counterparty = transfer.to_address
            elif transfer.to_address == address.value:
                direction = "in"
                counterparty = transfer.from_address

        if not labels:
            counterparty_type = "unknown"
        elif counterparty and labels.is_labelled(counterparty):
            counterparty_type = "exchange"
        else:
            counterparty_type = "unlabelled"

        return {
            "value": float(transfer.value.raw),
            "kind": "transfer",
            "direction": direction,
            "counterparty_type": counterparty_type,
            "counterparty": counterparty,
            "counterparty_entity": (
                labels.entity_of(counterparty) if counterparty and labels else None
            ),
            "tx_hash": transfer.tx_hash,
            "height": transfer.height,
            # No USD figure: A01 ingests no price feed, and a fabricated one
            # would trip the detector's USD floor on arbitrary transfers.
            "usd_value": 0.0,
        }


__all__ = ["DEFAULT_TRANSFER_LIMIT", "MIN_POPULATION", "WhaleTransferSkill"]
