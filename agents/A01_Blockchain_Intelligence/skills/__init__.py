"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    skills

Purpose:
    The capability layer. One skill answers one question from stored history.

Layer contract
--------------
A skill reads `database/`, applies its own policy, and returns a typed result.
It never calls another skill — combining them is `intelligence/`'s job — and it
never fetches from a chain, because a lookup whose answer depends on network
conditions at query time is not a lookup.

The property that makes this layer trustworthy
----------------------------------------------
Every result carries :class:`Coverage`: how much history the answer was computed
over, and whether that is enough to license a *negative* claim.

This is load-bearing rather than decorative. The database holds only what was
ingested, so "no activity found" is a statement about storage. Asked of a
four-block database, it is true of the database and false of the chain — and the
number itself shows no difference. A skill therefore consults
:attr:`Coverage.supports_absence` before reporting that something did not
happen, and withholds the field otherwise so the detector above reports "not
determinable" instead of a confident error.

Four skills are implemented. The other fifteen folders are a plan, and
:data:`skills.registry.PLANNED_SKILLS` records what each is waiting on rather
than leaving the absence unexplained.
"""

from __future__ import annotations

from .base import (
    MIN_BLOCKS_FOR_ABSENCE,
    Coverage,
    Skill,
    SkillRequest,
    SkillResult,
)
from .registry import (
    PLANNED_SKILLS,
    Readiness,
    SkillEntry,
    SkillRegistry,
    default_registry,
)
from .exchange_flow import ExchangeFlowSkill
from .token_flow import TokenFlowSkill
from .wallet_lookup import WalletProfileSkill
from .whale_detection import WhaleTransferSkill

__all__ = [
    "MIN_BLOCKS_FOR_ABSENCE",
    "PLANNED_SKILLS",
    "Coverage",
    "ExchangeFlowSkill",
    "Readiness",
    "Skill",
    "SkillEntry",
    "SkillRegistry",
    "SkillRequest",
    "SkillResult",
    "TokenFlowSkill",
    "WalletProfileSkill",
    "WhaleTransferSkill",
    "default_registry",
]
