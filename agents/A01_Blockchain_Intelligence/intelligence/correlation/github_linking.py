"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.correlation.github_linking

Purpose:
    Link GitHub accounts to subjects.
"""

from __future__ import annotations

from typing import Any

from .correlator import Correlation


class GithubLinker:
    """
    Links GitHub usernames/repos to subjects.
    """

    def link(self, subjects: list[dict[str, Any]]) -> list[Correlation]:
        correlations: list[Correlation] = []
        for subject in subjects:
            address = subject.get("address")
            github = subject.get("github")
            if not address or not github:
                continue
            correlations.append(
                Correlation(
                    left=str(address),
                    right=str(github),
                    relation="github",
                    confidence=0.75,
                )
            )
        return correlations
