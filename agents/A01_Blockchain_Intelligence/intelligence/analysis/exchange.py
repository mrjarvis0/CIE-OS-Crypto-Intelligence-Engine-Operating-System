"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.exchange

Purpose:
    Directional exchange flow over a window of attributed transfers
    (DET-EXCHANGE-01).

    Answers whether native value moved one way between ordinary addresses and
    labelled exchange addresses, or merely churned in both directions. It does
    not say why it moved.

What this detector refuses to do
--------------------------------
An inflow is not sell pressure. A deposit to an exchange is consistent with an
intent to sell, with posting collateral, with market making, and with an
operator migrating custody -- and native value alone cannot separate them. The
detection catalog puts classification strictly after analysis, so this module
reports direction and magnitude and stops. It never emits "sell pressure",
"accumulation", "distribution", "bullish" or "bearish".

Why an imbalance ratio rather than a raw total
----------------------------------------------
A window's net flow is the difference of two large numbers, and on its own it
says nothing about whether that difference is a signal. An exchange that took
in 900 ETH and paid out 880 has a net of +20, which is a rounding error on its
own traffic; one that took in 20 and paid out nothing has the same net and a
completely different shape.

So the measurement is ``|net| / (inflow + outflow)`` -- the share of all
attributed movement that did not cancel out. It is zero for a perfectly two-way
window and one for a purely one-way one, it is scale-free, and it is the same
number whatever the chain's unit is worth.

What bounds every figure here
-----------------------------
Three things, and all three are reported rather than implied.

**The label list is somebody else's claim.** That an address belongs to Binance
is an external assertion with its own provenance, so the evidence is
ATTRIBUTION tier and its confidence is capped at the confidence of the weakest
label the attribution could rest on. A community list loads at 0.5 and this
detector cannot exceed it -- the conclusion is worth no more than the list
behind it.

**Native value only.** The stablecoin traffic that dominates real exchange flow
is ERC-20 transfers, which A01 stores without label attribution. A window can
therefore read as an outflow in native value while the token flow ran the other
way, and nothing here would know.

**No exchange list is complete.** An unlabelled deposit address is invisible,
which biases every figure toward under-counting. The direction survives that
better than the magnitude does, which is why the direction is the claim.

See docs/intelligence/detection-catalog.md.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

from ..schemas.evidence import ClaimTier, EvidenceSource
from .base import AnalyzerResult, BaseAnalyzer

#: Attributed transfers below which a direction is noise. An imbalance computed
#: from three transfers is a statement about those three transfers, and one more
#: would reverse it.
MIN_ATTRIBUTED: Final[int] = 10

#: Share of gross attributed movement that must survive cancellation before the
#: window is called directional.
#:
#: A policy line, not a measurement: nothing has established where two-way churn
#: stops and a one-sided window starts, and this detector is registered as
#: IMPLEMENTED for exactly that reason. It is stated here, reported in the
#: result, and is the first thing a backtest should move.
DIRECTIONAL_RATIO: Final[float] = 0.20

#: Share of gross movement one operator must carry before the window is a fact
#: about that operator rather than about exchanges in general.
CONCENTRATION_RATIO: Final[float] = 0.80


class Direction:
    """
    What a window of attributed flow was.

    Deliberately not an interpretation scale. ``NET_INFLOW`` says value moved
    toward labelled exchange addresses and says nothing about why.
    """

    INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
    #: Labels loaded, window licensed, and nothing touched a labelled address.
    NO_ATTRIBUTED_FLOW = "NO_ATTRIBUTED_FLOW"
    #: Movement in both directions, neither side dominating.
    BALANCED = "BALANCED"
    NET_INFLOW = "NET_INFLOW"
    NET_OUTFLOW = "NET_OUTFLOW"


def _int(value: Any) -> int:
    """
    A value from the skill's result body as an exact integer.

    Amounts cross that boundary as decimal strings because they routinely
    exceed what a float holds without loss -- 2**53 wei is about 0.009 ether,
    so a float total is wrong for essentially every exchange.
    """
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def imbalance(inflow: int, outflow: int) -> float:
    """
    The share of gross attributed movement that did not cancel out.

    Zero when the two sides match exactly, one when everything went one way.
    Returns zero for an empty window rather than raising: a window with no
    value in it has no imbalance, and the caller has already decided whether
    that is answerable.
    """
    gross = inflow + outflow
    if gross <= 0:
        return 0.0
    return abs(inflow - outflow) / gross


class ExchangeFlowAnalyzer(BaseAnalyzer):
    """
    Direction of native value between ordinary addresses and labelled exchanges.

    Emits ATTRIBUTION evidence. That value moved is structural; that it moved
    to *Binance* rests on a list, and the tier has to say so.
    """

    name = "exchange_flow"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        address = self._address(subject)
        flow = self._get(subject, "exchange_flow")

        if not isinstance(flow, Mapping):
            # Either no labels are loaded or the skill declined. Both are
            # "the question could not be asked", which is not the same answer
            # as "no exchange flow happened".
            data = self._insufficient(
                address,
                "no exchange flow in the subject; either no address labels are "
                "loaded or the flow skill declined",
            )
            return self._result(data=data, evidence=[], summary=self._summary(address, data))

        totals = flow.get("totals") or {}
        attributed = int(flow.get("attributed", 0) or 0)
        inflow_value = _int(totals.get("inflow_value"))
        outflow_value = _int(totals.get("outflow_value"))
        internal_value = _int(totals.get("internal_value"))
        net = inflow_value - outflow_value
        gross = inflow_value + outflow_value

        measured = {
            "chain": flow.get("chain"),
            "label_source": flow.get("label_source", ""),
            "labelled_addresses": int(flow.get("labelled_addresses", 0) or 0),
            "labelled_entities": int(flow.get("labelled_entities", 0) or 0),
            "transfers_scanned": int(flow.get("transfers_scanned", 0) or 0),
            "attributed": attributed,
            "inflow_count": int(totals.get("inflow_count", 0) or 0),
            "outflow_count": int(totals.get("outflow_count", 0) or 0),
            "internal_count": int(totals.get("internal_count", 0) or 0),
            # Amounts stay strings on the way out for the same reason they
            # arrived as strings.
            "inflow_value": str(inflow_value),
            "outflow_value": str(outflow_value),
            "internal_value": str(internal_value),
            "net_value": str(net),
            "bounds": list(flow.get("bounds") or ()),
        }

        if attributed == 0:
            # The skill has already asked its window whether a zero is
            # licensed, including in the bounded form a selective capture
            # supports. Deciding it again here from a different gate would
            # produce two answers to one question.
            if not bool(flow.get("absence_licensed")):
                data = self._insufficient(
                    address,
                    "no transfer touched a labelled exchange address, and the "
                    "window cannot license an absence",
                    measured,
                )
                return self._result(
                    data=data, evidence=[], summary=self._summary(address, data)
                )

            data = {
                **measured,
                "address": address,
                "grade": Direction.NO_ATTRIBUTED_FLOW,
                "is_directional": False,
                "determinable": True,
                "imbalance": 0.0,
                "absence_floor": flow.get("absence_floor"),
                "thresholds": self._thresholds(),
                "not_claimed": self._not_claimed(),
            }
            return self._result(data=data, evidence=[], summary=self._summary(address, data))

        if attributed < MIN_ATTRIBUTED:
            data = self._insufficient(
                address,
                f"{attributed} attributed transfer(s); {MIN_ATTRIBUTED} needed "
                "before a direction means anything",
                measured,
            )
            return self._result(data=data, evidence=[], summary=self._summary(address, data))

        if gross <= 0:
            # Every attributed transfer carried zero native value -- contract
            # calls to a labelled address. There is nothing to take a direction
            # of, and reporting BALANCED would read as a measured result.
            data = self._insufficient(
                address,
                f"{attributed} transfer(s) reached a labelled address carrying "
                "no native value, so the window has no direction to measure",
                measured,
            )
            return self._result(data=data, evidence=[], summary=self._summary(address, data))

        ratio = imbalance(inflow_value, outflow_value)
        directional = ratio >= DIRECTIONAL_RATIO
        if not directional:
            grade = Direction.BALANCED
        elif net > 0:
            grade = Direction.NET_INFLOW
        else:
            grade = Direction.NET_OUTFLOW

        entities = flow.get("entities") or {}
        leader, share = self._concentration(entities, gross)

        data = {
            **measured,
            "address": address,
            "grade": grade,
            "is_directional": directional,
            "determinable": True,
            "imbalance": round(ratio, 4),
            "top_entity": leader,
            "top_entity_share": round(share, 4),
            "concentrated": share >= CONCENTRATION_RATIO,
            "entities_seen": len(entities),
            "method": "net over gross attributed native value, per labelled operator",
            "thresholds": self._thresholds(),
            "label_confidence": float(flow.get("label_confidence", 0.0) or 0.0),
            "not_claimed": self._not_claimed(),
        }

        evidence = []
        if directional:
            # Capped at the label list's own confidence. The direction is a fact
            # about transfers; that those transfers concern an exchange is a
            # claim from a file, and a conclusion cannot outrank the assertion
            # holding it up.
            ceiling = float(flow.get("label_confidence", 0.0) or 0.0) or 0.5
            evidence.append(
                self._evidence(
                    claim=(
                        f"{attributed} transfer(s) attributed to labelled exchange "
                        f"addresses on {flow.get('chain')} moved "
                        f"{'toward' if net > 0 else 'away from'} them on net "
                        f"({round(ratio * 100, 1)}% of gross attributed value)"
                    ),
                    data={
                        "grade": grade,
                        "imbalance": data["imbalance"],
                        "attributed": attributed,
                        "inflow_value": str(inflow_value),
                        "outflow_value": str(outflow_value),
                        "net_value": str(net),
                        "label_source": measured["label_source"],
                        "method": data["method"],
                    },
                    source_type=EvidenceSource.ON_CHAIN,
                    tier=ClaimTier.ATTRIBUTION,
                    confidence=ceiling,
                    completeness=("token_transfers", "unlabelled_addresses"),
                )
            )

        return self._result(
            data=data, evidence=evidence, summary=self._summary(address, data)
        )

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _thresholds() -> dict[str, Any]:
        return {
            "min_attributed": MIN_ATTRIBUTED,
            "directional_ratio": DIRECTIONAL_RATIO,
            "concentration_ratio": CONCENTRATION_RATIO,
        }

    @staticmethod
    def _not_claimed() -> str:
        return (
            "intent: a deposit is consistent with selling, with collateral, "
            "with market making and with a custody move, and native value "
            "cannot tell them apart"
        )

    @staticmethod
    def _concentration(
        entities: Mapping[str, Any], gross: int
    ) -> tuple[str | None, float]:
        """
        The operator carrying the largest share of gross attributed movement.

        Measured against the per-transfer gross rather than the sum of the
        per-operator rows: a transfer between two exchanges is recorded on both
        of them, so those rows add up to more than the value that moved.
        """
        if not entities or gross <= 0:
            return None, 0.0

        best: str | None = None
        best_value = 0
        for entity, row in entities.items():
            if not isinstance(row, Mapping):
                continue
            volume = _int(row.get("inflow_value")) + _int(row.get("outflow_value"))
            if volume > best_value:
                best, best_value = str(entity), volume

        if best is None:
            return None, 0.0
        return best, min(1.0, best_value / gross)

    @staticmethod
    def _insufficient(
        address: str | None,
        reason: str,
        measured: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            **(measured or {}),
            "address": address,
            "grade": Direction.INSUFFICIENT,
            "is_directional": False,
            "determinable": False,
            "reason": reason,
            "thresholds": ExchangeFlowAnalyzer._thresholds(),
        }

    @staticmethod
    def _summary(address: str | None, data: dict[str, Any]) -> str:
        subject = address or data.get("chain") or "window"
        if not data["determinable"]:
            return f"{subject}: exchange flow not determinable ({data['reason']})"

        if data["grade"] == Direction.NO_ATTRIBUTED_FLOW:
            return (
                f"{subject}: no transfer in the stored window touched one of the "
                f"{data['labelled_addresses']} labelled exchange address(es)"
            )

        share = f"{round(data['top_entity_share'] * 100)}%"
        where = (
            f"; {data['top_entity']} carried {share} of it"
            if data.get("top_entity")
            else ""
        )
        if not data["is_directional"]:
            return (
                f"{subject}: BALANCED — {data['attributed']} attributed transfer(s) "
                f"across {data['entities_seen']} operator(s), "
                f"{round(data['imbalance'] * 100, 1)}% of gross value uncancelled"
                f"{where}; direction only, no interpretation claimed"
            )
        return (
            f"{subject}: {data['grade']} — {data['attributed']} attributed "
            f"transfer(s), {round(data['imbalance'] * 100, 1)}% of gross value "
            f"one-way{where}; direction only, no interpretation claimed"
        )


__all__ = [
    "CONCENTRATION_RATIO",
    "DIRECTIONAL_RATIO",
    "MIN_ATTRIBUTED",
    "Direction",
    "ExchangeFlowAnalyzer",
    "imbalance",
]
