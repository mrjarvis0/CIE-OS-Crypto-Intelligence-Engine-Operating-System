"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.verification

Purpose:
    Cross-checking claims against external sources.

    Reduces hallucinations and false correlations by verifying
    conclusions against on-chain, web, social, and GitHub sources and
    aggregating consensus.

Submodules
----------
verifier     Central verification orchestrator.
cross_check  Cross-source claim checking.
blockchain   On-chain verification.
web          Web verification.
social       Social verification.
github       GitHub verification.
consensus    Consensus aggregation across sources.
"""

from __future__ import annotations

from .blockchain import BlockchainVerifier
from .consensus import ConsensusEngine
from .cross_check import CrossChecker
from .github import GithubVerifier
from .social import SocialVerifier
from .verifier import Verifier
from .web import WebVerifier

__all__ = [
    "Verifier",
    "CrossChecker",
    "BlockchainVerifier",
    "WebVerifier",
    "SocialVerifier",
    "GithubVerifier",
    "ConsensusEngine",
]
