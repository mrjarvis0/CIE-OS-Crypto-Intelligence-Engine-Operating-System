"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.verification.blockchain

Purpose:
    On-chain verification.
"""

from __future__ import annotations


class BlockchainVerifier:
    """
    Verifies claims against on-chain facts.
    """

    name = "blockchain"

    def verify(self, claim: str, facts: list[str] | None = None) -> bool:
        """
        Confirm a claim if it matches an expected on-chain fact.
        """
        facts = facts or []
        return claim in facts
