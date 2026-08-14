"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.reasoning.tree_of_thought

Purpose:
    Multi-branch tree-of-thought exploration over alternative paths.

    Auto-generated branches are textually distinct so their viability
    scores can differ; ties are broken deterministically toward the
    earliest branch, never arbitrarily.
"""

from __future__ import annotations

from typing import Any

from ..schemas.evidence import EvidenceArtifact
from .reasoning_engine import ReasoningStep

# Distinguishing tokens per auto-generated branch so each branch has a
# unique viability signature instead of identical token sets.
_DISTINCTORS = (
    "primary",
    "alternate",
    "contrary",
    "competing",
    "secondary",
    "counter",
    "parallel",
    "rival",
)


class TreeOfThought:
    """
    Explores multiple reasoning branches and ranks them by viability.

    Instead of committing to one path, it scores alternative hypotheses
    against available evidence and surfaces the best-supported branch
    while recording the rejected alternatives (aligning with the
    conservative, alternatives-aware attribution model).
    """

    def __init__(self, max_branches: int = 4) -> None:
        self._max_branches = max_branches

    def reason(
        self, question: str, context: dict[str, Any] | None = None, **_: Any
    ) -> list[ReasoningStep]:
        context = context or {}
        branches = int(context.get("branches", self._max_branches))
        evidence = [
            e for e in context.get("evidence", []) if isinstance(e, EvidenceArtifact)
        ]

        steps: list[ReasoningStep] = [ReasoningStep(kind="observation", content=question)]

        hypotheses = context.get("hypotheses", [])
        if not hypotheses:
            hypotheses = [
                f"alternative hypothesis #{i + 1} "
                f"({_DISTINCTORS[i % len(_DISTINCTORS)]} path)"
                for i in range(branches)
            ]

        scored: list[tuple[float, int, str]] = []
        for index, hypothesis in enumerate(hypotheses):
            viability = self._viability(str(hypothesis), evidence)
            scored.append((viability, -index, str(hypothesis)))
            steps.append(
                ReasoningStep(
                    kind="branch",
                    content=str(hypothesis),
                    metadata={"viability": round(viability, 4)},
                )
            )

        # Descending by score; equal scores resolve to the earliest
        # branch (negative index) rather than an arbitrary tie-break.
        scored.sort(reverse=True)
        best = scored[0][2] if scored else "no viable branch"
        rejected = [h for _, _, h in scored[1:]] if scored else []

        steps.append(
            ReasoningStep(
                kind="evaluation",
                content=f"ranked {len(scored)} branches by evidence support",
                metadata={"branches": len(scored)},
            )
        )
        steps.append(
            ReasoningStep(
                kind="conclusion",
                content=best,
                metadata={"rejected_alternatives": rejected},
            )
        )
        return steps

    def _viability(self, hypothesis: str, evidence: list[EvidenceArtifact]) -> float:
        """
        Score a hypothesis 0..1 by how many evidence items align with it.

        Token overlap with the hypothesis is used as a lightweight proxy
        for topical alignment.
        """
        if not evidence:
            return 0.0
        tokens = {w for w in hypothesis.lower().split() if len(w) > 2}
        if not tokens:
            return 0.0
        hits = 0.0
        for item in evidence:
            haystack = f"{item.claim} {item.reference or ''}".lower()
            if any(tok in haystack for tok in tokens):
                hits += item.confidence
        return min(1.0, hits / len(evidence))
