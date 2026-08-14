"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.attribution.heuristics

Purpose:
    Rule-based attribution heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Heuristic:
    """
    A rule producing an attribution label.

    Each heuristic records the category it claims and the evidence
    references that support it, so downstream confidence scoring can
    weigh corroboration against contradiction.
    """

    label: str
    category: str
    confidence: float
    evidence_refs: list[str] = field(default_factory=list)


class AttributionHeuristics:
    """
    Applies rule-based heuristics to infer likely entity categories.

    Rules are intentionally conservative: low-prevalence flags (mixer
    contact, bot behaviour) yield lower confidence than explicit labels
    (exchange, verified contract) that are corroborated.
    """

    def apply(self, subject: dict[str, Any]) -> list[Heuristic]:
        """
        Return heuristic attributions for a subject.

        Reads explicit labels first, then derives behaviour-based
        categories from on-chain signals with appropriate confidence.
        """
        results: list[Heuristic] = []
        raw_labels = subject.get("labels")
        if isinstance(raw_labels, str):
            raw_labels = [raw_labels]
        elif raw_labels is None:
            raw_labels = []
        try:
            labels = set(str(l) for l in raw_labels)
        except TypeError:
            labels = set()

        # Explicit / verified labels (strongest signals).
        if "exchange" in labels or subject.get("is_exchange"):
            results.append(
                Heuristic(
                    label="exchange",
                    category="exchange",
                    confidence=0.95,
                    evidence_refs=["label:exchange"],
                )
            )
        if subject.get("is_contract"):
            results.append(
                Heuristic(
                    label="contract",
                    category="contract",
                    confidence=0.95,
                    evidence_refs=["code:deployed"],
                )
            )
        if subject.get("verified_operator"):
            results.append(
                Heuristic(
                    label="operator",
                    category="operator",
                    confidence=0.98,
                    evidence_refs=["key:admin", "role:operator"],
                )
            )

        # Behaviour-derived signals (weaker, conservative).
        if subject.get("mixer_contact"):
            results.append(
                Heuristic(
                    label="mixer_user",
                    category="mixer",
                    confidence=0.6,
                    evidence_refs=["tx:to_mixer"],
                )
            )
        if subject.get("bridge_contact"):
            results.append(
                Heuristic(
                    label="bridge_user",
                    category="bridge",
                    confidence=0.55,
                    evidence_refs=["tx:to_bridge"],
                )
            )
        if subject.get("bot_detected"):
            results.append(
                Heuristic(
                    label="bot",
                    category="bot",
                    confidence=0.5,
                    evidence_refs=["behaviour:automated"],
                )
            )
        if subject.get("whale_criteria"):
            results.append(
                Heuristic(
                    label="whale",
                    category="whale",
                    confidence=0.7,
                    evidence_refs=["balance:threshold"],
                )
            )
        return results
