"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.correlation.pattern_matching

Purpose:
    Match behavioral patterns across subjects.
"""

from __future__ import annotations

from typing import Any

from .correlator import Correlation


class PatternMatcher:
    """
    Detects subjects sharing a characteristic pattern.
    """

    def __init__(self, pattern_key: str = "behavioral_pattern") -> None:
        self._pattern_key = pattern_key

    def link(self, subjects: list[dict[str, Any]]) -> list[Correlation]:
        correlations: list[Correlation] = []
        groups: dict[str, list[str]] = {}
        for subject in subjects:
            pattern = subject.get(self._pattern_key)
            address = subject.get("address")
            if not pattern or not address:
                continue
            groups.setdefault(str(pattern), []).append(str(address))

        for pattern, addresses in groups.items():
            for i in range(len(addresses)):
                for j in range(i + 1, len(addresses)):
                    correlations.append(
                        Correlation(
                            left=addresses[i],
                            right=addresses[j],
                            relation="shared_pattern",
                            confidence=0.5,
                        )
                    )
        return correlations
