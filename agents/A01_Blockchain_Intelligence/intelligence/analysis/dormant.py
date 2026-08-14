"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.dormant

Purpose:
    Dormant wallet reactivation analysis (DET-DORMANT-01).

    Detects the first outbound movement from a wallet that has been inactive
    for a long period while holding a materially large balance.

Why this detector is prioritised
--------------------------------
Most on-chain detectors fight a base-rate problem: the behaviour they look
for is common, benign explanations are numerous, and the posterior
probability of the interesting case stays low however good the detector is.

Dormant reactivation is the opposite. Long-dormant large holders are
genuinely rare, and the set of benign explanations is small and enumerable.
That combination gives it the best signal-to-noise ratio of any detector in
the catalog, which is why it is built first.

For a trader the signal is supply overhang: coins that were effectively
removed from the float re-entering circulation, often ahead of distribution.

See docs/intelligence/detection-catalog.md section 3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..schemas.evidence import ClaimTier, EvidenceSource
from .base import AnalyzerResult, BaseAnalyzer

#: A year of silence. Shorter windows pick up ordinary infrequent users.
DEFAULT_DORMANCY_DAYS = 365

#: Only large holders matter here: a dormant dust wallet waking up is noise.
DEFAULT_BALANCE_PERCENTILE = 99.0

#: Dormancy bands, in days. Reported alongside the raw figure because "woke
#: after 6 years" and "woke after 13 months" are different events.
DORMANCY_BANDS: tuple[tuple[int, str], ...] = (
    (2555, "ancient"),      # 7y+ -- early-era holder
    (1460, "very_long"),    # 4y+
    (730, "long"),          # 2y+
    (365, "standard"),      # 1y+
)

#: Benign explanations that must be excluded before reporting. Each is a
#: real pattern that would otherwise dominate the alert stream.
BENIGN_CONTEXTS = frozenset(
    {
        "vesting_unlock",     # scheduled, publicly known
        "staking_unbond",     # protocol-driven, not a holder decision
        "custody_migration",  # custodian moving cold storage
        "airdrop_claim",      # recipient claiming, not a holder selling
        "contract_upgrade",
    }
)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if result != result else result


def _parse_time(value: Any) -> datetime | None:
    """Parse an ISO-8601 string, epoch seconds, or datetime into aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _band(days: float) -> str:
    for threshold, label in DORMANCY_BANDS:
        if days >= threshold:
            return label
    return "none"


class DormantAnalyzer(BaseAnalyzer):
    """
    Detects reactivation of long-dormant, materially large wallets.

    Emits STRUCTURAL evidence: the timing and size of the movement are
    observations about the chain. No claim is made about who the holder is or
    why they moved -- that would be an attribution, with a far lower ceiling.
    """

    name = "dormant"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        address = self._address(subject)
        now = _parse_time(self._get(subject, "as_of")) or datetime.now(UTC)

        last_outbound = _parse_time(self._get(subject, "last_outbound_at"))
        first_seen = _parse_time(self._get(subject, "first_seen_at"))
        reference = last_outbound or first_seen

        min_days = _to_float(
            self._get(subject, "dormancy_days"), DEFAULT_DORMANCY_DAYS
        )
        min_percentile = _to_float(
            self._get(subject, "balance_percentile"), DEFAULT_BALANCE_PERCENTILE
        )

        balance = _to_float(self._get(subject, "balance"))
        balance_percentile = self._get(subject, "balance_percentile_rank")
        balance_percentile = (
            _to_float(balance_percentile) if balance_percentile is not None else None
        )

        context = str(self._get(subject, "movement_context", "") or "").lower()
        benign = context in BENIGN_CONTEXTS
        has_moved = bool(self._get(subject, "reactivated", False))

        dormancy_days = (
            (now - reference).total_seconds() / 86400.0 if reference else None
        )

        # Determinability is reported separately from the negative result:
        # "not dormant" and "cannot tell" are different claims, and conflating
        # them is a factual error the evidence standard forbids.
        determinable = reference is not None and has_moved is not None

        is_dormant = dormancy_days is not None and dormancy_days >= min_days
        is_material = (
            balance_percentile is None or balance_percentile >= min_percentile
        ) and balance > 0
        reactivated = bool(is_dormant and is_material and has_moved and not benign)

        data: dict[str, Any] = {
            "address": address,
            "reactivated": reactivated,
            "dormancy_days": round(dormancy_days, 2) if dormancy_days else None,
            "dormancy_band": _band(dormancy_days) if dormancy_days else "none",
            "last_outbound_at": last_outbound.isoformat() if last_outbound else None,
            "balance": balance or None,
            "balance_percentile_rank": balance_percentile,
            "is_dormant": is_dormant,
            "is_material": is_material,
            "movement_context": context or None,
            "suppressed_as_benign": benign,
            "determinable": determinable,
            "thresholds": {
                "dormancy_days": min_days,
                "balance_percentile": min_percentile,
            },
            "signal": self._signal(reactivated, balance, _band(dormancy_days) if dormancy_days else "none"),
        }

        evidence = []
        if reactivated:
            evidence.append(
                self._evidence(
                    claim=f"dormant wallet {address} reactivated",
                    data={
                        "address": address,
                        "dormancy_days": data["dormancy_days"],
                        "dormancy_band": data["dormancy_band"],
                        "balance": balance,
                    },
                    source_type=EvidenceSource.ON_CHAIN,
                    tier=ClaimTier.STRUCTURAL,
                    confidence=0.9,
                    completeness=("external",),
                )
            )

        return self._result(
            data=data,
            evidence=evidence,
            summary=self._summary(address, data),
        )

    @staticmethod
    def _signal(reactivated: bool, balance: float, band: str) -> dict[str, Any]:
        """
        Trading interpretation, stated explicitly rather than left implicit.

        Longer dormancy implies a larger share of the balance was outside the
        effective float, so reactivation returns more supply to circulation.
        """
        if not reactivated:
            return {"type": "none", "interpretation": "no reactivation observed"}

        severity = {
            "ancient": "high",
            "very_long": "high",
            "long": "medium",
            "standard": "low",
        }.get(band, "low")

        return {
            "type": "supply_overhang",
            "severity": severity,
            "balance_returning_to_float": balance or None,
            "interpretation": (
                "long-held supply re-entering circulation; "
                "watch for follow-on distribution to exchanges"
            ),
        }

    @staticmethod
    def _summary(address: str | None, data: dict[str, Any]) -> str:
        if not data["determinable"]:
            return f"{address}: dormancy not determinable (no activity history supplied)"
        if data["suppressed_as_benign"]:
            return (
                f"{address}: movement after {data['dormancy_days']}d dormancy "
                f"suppressed as {data['movement_context']}"
            )
        if not data["reactivated"]:
            return f"{address}: no dormant reactivation observed"
        return (
            f"{address}: reactivated after {data['dormancy_days']}d "
            f"({data['dormancy_band']}); {data['signal']['severity']} supply overhang"
        )
