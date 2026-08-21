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

All nineteen skills are implemented. Each is registered as LIMITED and states
what it cannot see. :func:`skills.registry.default_registry` returns the full
set.
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
from .bridge import BridgeSkill
from .cross_chain import CrossChainSkill
from .defi import DefiSkill
from .developer_activity import DeveloperActivitySkill
from .exchange_flow import ExchangeFlowSkill
from .governance import GovernanceSkill
from .mining import MiningSkill
from .network_health import NetworkHealthSkill
from .nft import NftSkill
from .security import SecuritySkill
from .smart_contract import SmartContractSkill
from .smart_money import SmartMoneySkill
from .stablecoin import StablecoinSkill
from .staking import StakingSkill
from .token_flow import TokenFlowSkill
from .token_unlock import TokenUnlockSkill
from .validator import ValidatorSkill
from .wallet_lookup import WalletProfileSkill
from .whale_detection import WhaleTransferSkill

__all__ = [
    "MIN_BLOCKS_FOR_ABSENCE",
    "PLANNED_SKILLS",
    "BridgeSkill",
    "Coverage",
    "CrossChainSkill",
    "DefiSkill",
    "DeveloperActivitySkill",
    "ExchangeFlowSkill",
    "GovernanceSkill",
    "MiningSkill",
    "NetworkHealthSkill",
    "NftSkill",
    "Readiness",
    "SecuritySkill",
    "Skill",
    "SkillEntry",
    "SkillRegistry",
    "SkillRequest",
    "SkillResult",
    "SmartContractSkill",
    "SmartMoneySkill",
    "StablecoinSkill",
    "StakingSkill",
    "TokenFlowSkill",
    "TokenUnlockSkill",
    "ValidatorSkill",
    "WalletProfileSkill",
    "WhaleTransferSkill",
    "default_registry",
]
