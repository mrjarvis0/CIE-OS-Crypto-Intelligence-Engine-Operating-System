"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.evidence.source_rank

Purpose:
    Rank evidence sources by reliability to weight confidence.
"""

from __future__ import annotations

from ..schemas.evidence import EvidenceSource

# Default reliability (0..1) per source category.
_SOURCE_RELIABILITY: dict[EvidenceSource, float] = {
    EvidenceSource.ON_CHAIN: 1.0,
    EvidenceSource.EXPLORER: 0.95,
    EvidenceSource.GOVERNMENT: 0.9,
    EvidenceSource.DOCUMENTATION: 0.85,
    EvidenceSource.MARKET: 0.8,
    EvidenceSource.GITHUB: 0.75,
    EvidenceSource.NEWS: 0.6,
    EvidenceSource.SOCIAL: 0.35,
    EvidenceSource.ANALYST: 0.7,
    EvidenceSource.AI: 0.4,
    EvidenceSource.INFERRED: 0.2,
}


class SourceRanker:
    """
    Provides a reliability weight for each evidence source category.
    """

    def __init__(self, overrides: dict[EvidenceSource | str, float] | None = None) -> None:
        self._reliability = dict(_SOURCE_RELIABILITY)
        if overrides:
            for key, value in overrides.items():
                try:
                    self._reliability[EvidenceSource(key)] = max(0.0, min(1.0, value))
                except ValueError:
                    continue

    def reliability(self, source: EvidenceSource | str) -> float:
        """
        Return the reliability weight for a source category.
        """
        try:
            key = EvidenceSource(source)
        except ValueError:
            return 0.0
        return self._reliability.get(key, 0.0)
