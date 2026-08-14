"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.verification.social

Purpose:
    Social verification.
"""

from __future__ import annotations


class SocialVerifier:
    """
    Verifies claims against social media content.
    """

    name = "social"

    def verify(self, claim: str, posts: list[str] | None = None) -> bool:
        """
        Confirm a claim if it appears in a known social post.
        """
        posts = posts or []
        return any(claim in post for post in posts)
