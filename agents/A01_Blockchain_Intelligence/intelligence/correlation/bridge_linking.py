"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.correlation.bridge_linking

Purpose:
    Link wallet pairs across bridge transactions.
"""

from __future__ import annotations

from typing import Any

from .correlator import Correlation


class BridgeLinker:
    """
    Detects same-owner wallet pairs across bridge transactions.
    """

    def link(self, subjects: list[dict[str, Any]]) -> list[Correlation]:
        correlations: list[Correlation] = []
        seen: set[tuple[str, str]] = set()
        for subject in subjects:
            address = subject.get("address")
            if not address:
                continue
            for remote in subject.get("bridge_counterparts", []):
                if not remote or str(remote) == str(address):
                    continue
                pair = tuple(sorted((str(address), str(remote))))
                if pair in seen:
                    continue
                seen.add(pair)
                correlations.append(
                    Correlation(
                        left=pair[0],
                        right=pair[1],
                        relation="bridge_linked",
                        confidence=0.65,
                    )
                )
        return correlations
