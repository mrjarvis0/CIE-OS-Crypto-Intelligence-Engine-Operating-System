"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.wallet_lookup.profile

Purpose:
    Describe one address from stored history: when it was first and last seen,
    how much moved in each direction, and how many counterparties it touched.

Design goals:
    - Facts and counts; no judgement about what the address is
    - Dormancy reported only when the window can support it
    - An unseen address distinguished from an address with no activity
    - Feeds the dormant detector's subject without deciding its verdict

Notes:
    The distinction this skill must never lose is between *not in the window*
    and *not active*. An address absent from four stored blocks is almost
    certainly a busy address the window did not reach. Reporting it as inactive
    produces the most confident wrong answer in the system, because the dormancy
    detector's whole premise -- long-dormant large holders are rare -- inverts
    when every address looks dormant.

    So ``last_outbound_at`` is emitted into the subject only when
    :attr:`Coverage.supports_absence` holds. Without that, the field is withheld
    and the detector reports "not determinable", which is the correct answer.
    Withholding a field is better than supplying a wrong one: the detector
    already handles a missing field honestly, and it has no way to notice a
    plausible lie.

    No balance is reported. Storage holds transfers, not state, so a balance
    would have to be reconstructed by summing the stored window -- which is a
    partial sum presented as a balance. The dormancy detector's materiality
    check therefore stays unsatisfied until a balance sensor exists, and it
    declines rather than guessing.
"""

from __future__ import annotations

from typing import Any

from database.analytics import SqliteAnalyticsRepository

from ..base import Coverage, Skill, SkillRequest, SkillResult


class WalletProfileSkill(Skill):
    """
    Resolves an address to what stored history says about it.

    One responsibility: describe the address. Whether the description amounts
    to a dormant whale, an exchange hot wallet, or a contract is decided
    elsewhere against thresholds this skill does not hold.
    """

    name = "wallet_profile"
    description = "First/last activity, volumes and counterparties for one address"

    def run(
        self, request: SkillRequest, analytics: SqliteAnalyticsRepository
    ) -> SkillResult:
        coverage = self.coverage_for(request, analytics)

        if request.address is None:
            return self.undetermined(coverage, "wallet_profile requires an address")
        if coverage.empty:
            return self.undetermined(
                coverage, f"no {request.chain} history stored to profile against"
            )

        summary = analytics.address_summary(request.address)

        data: dict[str, Any] = {
            "address": request.address.value,
            "chain": request.chain,
            "seen_in_window": summary.seen,
            "sent_count": summary.sent_count,
            "received_count": summary.received_count,
            "transaction_count": summary.transaction_count,
            "sent_total": summary.sent_total.as_dict(),
            "received_total": summary.received_total.as_dict(),
            "sent_units": summary.sent_total.format(6),
            "received_units": summary.received_total.format(6),
            "counterparties": summary.counterparties,
            # A capped total is a floor. Reporting it unlabelled would present
            # a partial sum as the address's volume, which is the same class of
            # error as reading a shallow window as an absence.
            "totals_are_floors": summary.totals_capped,
            "first_height": summary.first_height,
            "last_height": summary.last_height,
            "first_seen_at": (
                summary.first_seen_at.isoformat() if summary.first_seen_at else None
            ),
            "last_seen_at": (
                summary.last_seen_at.isoformat() if summary.last_seen_at else None
            ),
            "last_outbound_at": (
                summary.last_outbound_at.isoformat()
                if summary.last_outbound_at
                else None
            ),
            # Stated so a consumer never has to infer it from the counts.
            "absence_meaningful": coverage.supports_absence,
            "coverage_limitation": coverage.limitation,
        }

        subject = self._subject(request, summary, coverage)

        if not summary.seen:
            reason = (
                "address not present in stored history; "
                + (
                    "the window is deep enough for that to mean inactivity"
                    if coverage.supports_absence
                    else coverage.limitation
                )
            )
            return self.answer(coverage, data, subject, reason)

        return self.answer(
            coverage,
            data,
            subject,
            f"{summary.transaction_count} transaction(s) in stored history",
        )

    def _subject(
        self,
        request: SkillRequest,
        summary: Any,
        coverage: Coverage,
    ) -> dict[str, Any]:
        """
        The fields this skill contributes to an analyzer subject.

        Timing fields are withheld unless the window supports an absence claim.
        A `last_outbound_at` derived from a shallow window would tell the
        dormancy detector that a busy address has been silent for a year, and
        the detector has no way to see that the figure is an artefact of how
        little was stored.
        """
        subject: dict[str, Any] = {
            "address": request.address.value if request.address else None,
            "chain": request.chain,
            "counterparty_count": summary.counterparties,
            "observed_transaction_count": summary.transaction_count,
        }

        if not coverage.supports_absence:
            subject["dormancy_determinable"] = False
            return subject

        subject["dormancy_determinable"] = True
        if summary.first_seen_at is not None:
            subject["first_seen_at"] = summary.first_seen_at.isoformat()
        if summary.last_outbound_at is not None:
            subject["last_outbound_at"] = summary.last_outbound_at.isoformat()
            subject["reactivated"] = True

        # Deliberately no `balance`: storage holds transfers, not state, so any
        # figure here would be a partial sum wearing a balance's name. The
        # dormancy detector declines on the missing field, which is correct.
        return subject


__all__ = ["WalletProfileSkill"]
