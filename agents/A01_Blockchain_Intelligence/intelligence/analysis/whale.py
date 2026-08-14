"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.whale

Purpose:
    Whale activity analysis (DET-WHALE-01).

    Identifies transfers large enough to matter *relative to their own
    market*, classifies the resulting flow as accumulation or distribution,
    and reports the exchange-flow direction that determines whether the
    activity implies sell pressure or supply removal.

Why thresholds are relative
---------------------------
The previous implementation used a bare ``threshold = 1000`` with no unit,
asset, or chain context. 1000 USDC is a retail payment; 1000 BTC is a
market-moving event; 1000 wei is dust. An absolute threshold is also a
published evasion guide -- an adversary simply sits below it.

This analyzer therefore qualifies a transfer on three relative measures and
requires the strongest available one to trip:

* percentile rank within the asset's own recent transfer distribution
* fraction of circulating supply
* USD notional, used only as a floor to exclude economically trivial
  transfers that happen to rank highly in a thin market

See docs/intelligence/detection-catalog.md section 3.
"""

from __future__ import annotations

from typing import Any

from ..schemas.evidence import ClaimTier, ErrorRate, EvidenceSource
from .base import AnalyzerResult, BaseAnalyzer

# Defaults. Every one is overridable per subject, because a sensible whale
# threshold for a blue-chip asset is nonsense for a long-tail token.
DEFAULT_PERCENTILE = 99.9
DEFAULT_SUPPLY_FRACTION = 0.001
DEFAULT_USD_FLOOR = 1_000_000.0

#: Transfer kinds that are not economic movements of exposure and must be
#: folded out before anything is measured. Counting these is what turns a
#: whale detector into a noise generator.
SUPPRESSED_KINDS = frozenset(
    {
        "internal",       # same-cluster custody rebalancing
        "bridge_lock",    # paired with a mint on the destination chain
        "bridge_mint",
        "wrap",           # ETH -> WETH is not a change in exposure
        "unwrap",
        "rebase",
        "router_hop",     # DEX aggregator intermediate leg
        "initial_mint",   # deployment mint is 100% of supply by definition
    }
)

#: Error rate is unmeasured until backtested against a labelled window, which
#: caps every claim this analyzer makes at 0.60 confidence. That cap is the
#: honest position, not a limitation to work around.
WHALE_ERROR_RATE = ErrorRate()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    # NaN fails every comparison silently, which would let a poisoned feed
    # suppress detection rather than trip it.
    return default if result != result else result


def _percentile(sorted_values: list[float], value: float) -> float:
    """
    Percentile rank of ``value`` within ``sorted_values`` (0..100).

    Uses the count of strictly-smaller observations, so the largest transfer
    in a population does not automatically read as exactly 100.
    """
    if not sorted_values:
        return 0.0
    below = sum(1 for v in sorted_values if v < value)
    return (below / len(sorted_values)) * 100.0


class Transfer:
    """Normalized view of one transfer entry."""

    __slots__ = ("value", "kind", "direction", "counterparty_type", "usd")

    def __init__(self, raw: Any) -> None:
        if isinstance(raw, dict):
            self.value = _to_float(raw.get("value"))
            self.kind = str(raw.get("kind", "transfer")).lower()
            self.direction = str(raw.get("direction", "unknown")).lower()
            self.counterparty_type = str(
                raw.get("counterparty_type", "unknown")
            ).lower()
            self.usd = _to_float(raw.get("usd_value"), default=0.0)
        else:
            self.value = _to_float(raw)
            self.kind = "transfer"
            self.direction = "unknown"
            self.counterparty_type = "unknown"
            self.usd = 0.0

    @property
    def suppressed(self) -> bool:
        return self.kind in SUPPRESSED_KINDS


class WhaleAnalyzer(BaseAnalyzer):
    """
    Detects and characterizes whale activity for a subject.

    Emits STRUCTURAL evidence only: that a large transfer occurred is an
    observation about the chain, not a claim about who made it. Attributing
    the transfer to an entity is a separate, lower-ceilinged claim handled by
    ``intelligence/attribution``.
    """

    name = "whale"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        address = self._address(subject)
        raw_transfers = self._get(subject, "large_transfers", []) or []

        transfers = [Transfer(t) for t in raw_transfers]
        suppressed = [t for t in transfers if t.suppressed]
        qualifying = [t for t in transfers if not t.suppressed and t.value > 0]

        thresholds = self._thresholds(subject)
        population = sorted(
            _to_float(v) for v in (self._get(subject, "transfer_population", []) or [])
        )
        supply = _to_float(self._get(subject, "circulating_supply"), default=0.0)

        assessed = [
            self._assess(t, population, supply, thresholds) for t in qualifying
        ]
        triggering = [a for a in assessed if a["qualifies"]]

        flow = self._flow(qualifying)
        is_whale = bool(triggering)

        data: dict[str, Any] = {
            "address": address,
            "is_whale": is_whale,
            "large_transfer_count": len(qualifying),
            "qualifying_transfer_count": len(triggering),
            "suppressed_transfer_count": len(suppressed),
            "suppressed_kinds": sorted({t.kind for t in suppressed}),
            "largest_value": max((t.value for t in qualifying), default=None),
            "thresholds": thresholds,
            "population_size": len(population),
            "triggers": [a["trigger"] for a in triggering],
            "flow": flow,
            # Stated so a consumer can tell "no whale activity" from
            # "cannot determine", which are different claims.
            "determinable": bool(population) or supply > 0 or any(t.usd for t in qualifying),
        }

        evidence = []
        if is_whale:
            evidence.append(
                self._evidence(
                    claim=f"whale-scale transfer observed for {address}",
                    data={
                        "address": address,
                        "qualifying": len(triggering),
                        "triggers": data["triggers"],
                        "largest_value": data["largest_value"],
                    },
                    source_type=EvidenceSource.ON_CHAIN,
                    tier=ClaimTier.STRUCTURAL,
                    confidence=0.9,
                )
            )

        return self._result(
            data=data,
            evidence=evidence,
            summary=self._summary(address, data),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _thresholds(self, subject: dict[str, Any]) -> dict[str, float]:
        return {
            "percentile": _to_float(
                self._get(subject, "whale_percentile"), DEFAULT_PERCENTILE
            ),
            "supply_fraction": _to_float(
                self._get(subject, "whale_supply_fraction"),
                DEFAULT_SUPPLY_FRACTION,
            ),
            "usd_floor": _to_float(
                self._get(subject, "whale_usd_floor"), DEFAULT_USD_FLOOR
            ),
        }

    @staticmethod
    def _assess(
        transfer: Transfer,
        population: list[float],
        supply: float,
        thresholds: dict[str, float],
    ) -> dict[str, Any]:
        """
        Decide whether one transfer is whale-scale, and say which measure
        made it so.

        Recording the trigger matters: "top 0.1% of transfers" and "2% of
        supply" are different findings with different implications, and a
        bare boolean throws that away.
        """
        rank = _percentile(population, transfer.value) if population else None
        fraction = (transfer.value / supply) if supply > 0 else None

        by_percentile = rank is not None and rank >= thresholds["percentile"]
        by_supply = fraction is not None and fraction >= thresholds["supply_fraction"]
        # USD is a floor, not a trigger on its own: it excludes economically
        # trivial transfers that rank highly only because the market is thin.
        meets_usd_floor = transfer.usd >= thresholds["usd_floor"] if transfer.usd else True

        qualifies = (by_percentile or by_supply) and meets_usd_floor

        if by_supply and by_percentile:
            trigger = "percentile+supply"
        elif by_supply:
            trigger = "supply_fraction"
        elif by_percentile:
            trigger = "percentile"
        else:
            trigger = None

        return {
            "qualifies": qualifies,
            "trigger": trigger,
            "percentile": rank,
            "supply_fraction": fraction,
            "usd_value": transfer.usd or None,
        }

    @staticmethod
    def _flow(transfers: list[Transfer]) -> dict[str, Any]:
        """
        Classify net flow direction and exchange exposure.

        This is the part a trader actually acts on. A large transfer is
        neutral information; a large transfer *into* an exchange is potential
        sell pressure, and one *out of* an exchange is supply leaving the
        liquid float.
        """
        inbound = sum(t.value for t in transfers if t.direction == "in")
        outbound = sum(t.value for t in transfers if t.direction == "out")

        to_exchange = sum(
            t.value
            for t in transfers
            if t.direction == "out" and t.counterparty_type == "exchange"
        )
        from_exchange = sum(
            t.value
            for t in transfers
            if t.direction == "in" and t.counterparty_type == "exchange"
        )

        net = inbound - outbound
        if inbound == 0 and outbound == 0:
            posture = "unknown"
        elif net > 0:
            posture = "accumulation"
        elif net < 0:
            posture = "distribution"
        else:
            posture = "neutral"

        # Whether the counterparties were checked at all, which is a different
        # question from what the check found. Before address labels existed the
        # skill sent every transfer through as ``unknown`` and this method read
        # the resulting zeros as "no exchange interaction observed" -- a
        # negative claim about the chain produced by never having looked.
        checked = any(t.counterparty_type != "unknown" for t in transfers)

        exchange_net = from_exchange - to_exchange
        if not checked:
            exchange_signal = "undetermined"
        elif to_exchange == 0 and from_exchange == 0:
            exchange_signal = "none"
        elif exchange_net < 0:
            exchange_signal = "deposit_to_exchange"
        elif exchange_net > 0:
            exchange_signal = "withdrawal_from_exchange"
        else:
            exchange_signal = "balanced"

        return {
            "inbound": inbound,
            "outbound": outbound,
            "net": net,
            "posture": posture,
            "to_exchange": to_exchange,
            "from_exchange": from_exchange,
            "exchange_signal": exchange_signal,
            "counterparties_checked": checked,
            # Spelled out so downstream consumers do not have to re-derive
            # the interpretation and risk getting the sign backwards.
            "interpretation": {
                "deposit_to_exchange": "potential sell pressure",
                "withdrawal_from_exchange": "supply leaving liquid float",
                "balanced": "no net exchange exposure change",
                # "None" is now licensed: the list was consulted and named no
                # counterparty. It still bounds itself, because an address the
                # list omits is invisible to it.
                "none": "no interaction with a labelled exchange address",
                "undetermined": (
                    "exchange interaction not determinable; no address labels "
                    "were loaded to check the counterparties against"
                ),
            }[exchange_signal],
        }

    @staticmethod
    def _summary(address: str | None, data: dict[str, Any]) -> str:
        if not data["is_whale"]:
            if not data["determinable"]:
                return (
                    f"{address}: whale status not determinable "
                    "(no population, supply, or USD reference supplied)"
                )
            return f"{address}: no whale-scale transfers observed"

        flow = data["flow"]
        return (
            f"{address}: {data['qualifying_transfer_count']} whale-scale "
            f"transfer(s) [{', '.join(t for t in data['triggers'] if t)}]; "
            f"posture={flow['posture']}, {flow['interpretation']}"
        )
