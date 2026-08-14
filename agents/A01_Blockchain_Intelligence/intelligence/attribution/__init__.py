"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    intelligence.attribution

Purpose:
    Identify who or what a subject is.

    Combines labels, identities, ownership, and heuristics to attribute
    a wallet or contract to an exchange, whale, hacker, DAO, bridge,
    bot, MEV, mixer, or institution.

Submodules
----------
attribution  Central attribution engine.
labels       Entity label management.
identity     Identity resolution.
ownership    Ownership attribution.
heuristics   Rule-based attribution heuristics.
confidence   Attribution confidence scoring.
"""

from __future__ import annotations

from .attribution import Attribution, AttributionEngine
from .confidence import AttributionConfidence
from .heuristics import AttributionHeuristics
from .identity import IdentityResolver
from .labels import LabelStore
from .ownership import OwnershipResolver

__all__ = [
    "Attribution",
    "AttributionEngine",
    "LabelStore",
    "IdentityResolver",
    "OwnershipResolver",
    "AttributionHeuristics",
    "AttributionConfidence",
]
