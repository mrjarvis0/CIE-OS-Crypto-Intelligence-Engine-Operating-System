"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.correlation

Purpose:
    Cross-source correlation to surface hidden relationships.

    Links wallets, entities, social accounts, GitHub accounts, bridges,
    and exchanges into unified identities and clusters.

Submodules
----------
correlator       Central correlation orchestrator.
wallet_linking   Link wallets via shared transactions.
entity_linking   Link identifiers to a unified entity.
social_linking   Link social identities.
github_linking   Link GitHub accounts.
bridge_linking   Link wallet pairs across bridges.
exchange_linking Link wallets to exchange addresses.
pattern_matching Match behavioral patterns across subjects.
cluster          Cluster related subjects.
"""

from __future__ import annotations

from .bridge_linking import BridgeLinker
from .cluster import Clusterer
from .correlator import Correlator
from .entity_linking import EntityLinker
from .exchange_linking import ExchangeLinker
from .github_linking import GithubLinker
from .pattern_matching import PatternMatcher
from .social_linking import SocialLinker
from .wallet_linking import WalletLinker

__all__ = [
    "Correlator",
    "WalletLinker",
    "EntityLinker",
    "SocialLinker",
    "GithubLinker",
    "BridgeLinker",
    "ExchangeLinker",
    "PatternMatcher",
    "Clusterer",
]
