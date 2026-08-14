"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.correlation.social_linking

Purpose:
    Link social identities (Twitter/X, Telegram, Discord) to subjects.
"""

from __future__ import annotations

from typing import Any

from .correlator import Correlation


class SocialLinker:
    """
    Links social handles to subjects.
    """

    def link(self, subjects: list[dict[str, Any]]) -> list[Correlation]:
        correlations: list[Correlation] = []
        for subject in subjects:
            address = subject.get("address")
            social = subject.get("social", {})
            for platform, handle in social.items():
                if not address or not handle:
                    continue
                correlations.append(
                    Correlation(
                        left=str(address),
                        right=f"{platform}:{handle}",
                        relation=f"social_{platform}",
                        confidence=0.6,
                    )
                )
        return correlations
