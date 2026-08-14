"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.verification.github

Purpose:
    GitHub verification.
"""

from __future__ import annotations


class GithubVerifier:
    """
    Verifies claims against GitHub repository content.
    """

    name = "github"

    def verify(self, claim: str, repo_content: list[str] | None = None) -> bool:
        """
        Confirm a claim if it matches repository content.
        """
        repo_content = repo_content or []
        return any(claim in content for content in repo_content)
