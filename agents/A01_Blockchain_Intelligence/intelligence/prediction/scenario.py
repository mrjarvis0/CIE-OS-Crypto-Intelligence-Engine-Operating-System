"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.prediction.scenario

Purpose:
    Scenario generation.

    Probabilities are normalized to sum to exactly 1.0 so that the
    scenario set forms a proper probability distribution over mutually
    exclusive futures. All-zero input probabilities fall back to a
    uniform distribution.
"""

from __future__ import annotations

from typing import Any

from ..schemas.prediction import Scenario
from ..utils.helpers import new_id


class ScenarioGenerator:
    """
    Generates conditional alternative futures.

    Probabilities are normalized to sum to 1.0 so that the scenario set
    forms a proper probability distribution over mutually exclusive
    futures.
    """

    def generate(
        self,
        subject: dict[str, Any],
        scenarios: list[dict[str, Any]] | None = None,
        **_: Any,
    ) -> list[Scenario]:
        """
        Build Scenario objects from definitions.

        Definitions supply ``name``, optional ``probability``, and
        optional ``conditions``/``outcomes``.
        """
        definitions = scenarios or [
            {"name": "bullish", "probability": 0.4},
            {"name": "base", "probability": 0.4},
            {"name": "bearish", "probability": 0.2},
        ]

        raw: list[dict[str, Any]] = []
        for d in definitions:
            raw.append(
                {
                    "name": str(d["name"]),
                    "probability": max(0.0, float(d.get("probability", 0.0))),
                    "conditions": tuple(d.get("conditions", [])),
                    "outcomes": dict(d.get("outcomes", {})),
                }
            )

        total = sum(r["probability"] for r in raw)
        if total <= 0:
            # No usable probabilities: fall back to a uniform
            # distribution so the set still sums to 1.0.
            share = 1.0 / len(raw) if raw else 1.0
            raw = [{**r, "probability": share} for r in raw]
            total = sum(r["probability"] for r in raw)

        normalized: list[Scenario] = []
        if raw:
            for r in raw[:-1]:
                normalized.append(
                    Scenario(
                        scenario_id=new_id("scen"),
                        name=r["name"],
                        probability=round(r["probability"] / total, 4),
                        conditions=r["conditions"],
                        outcomes=r["outcomes"],
                    )
                )
            # Final scenario absorbs rounding so the set sums to exactly 1.0.
            last = raw[-1]
            remainder = round(1.0 - sum(s.probability for s in normalized), 4)
            normalized.append(
                Scenario(
                    scenario_id=new_id("scen"),
                    name=last["name"],
                    probability=max(0.0, remainder),
                    conditions=last["conditions"],
                    outcomes=last["outcomes"],
                )
            )
        return normalized
