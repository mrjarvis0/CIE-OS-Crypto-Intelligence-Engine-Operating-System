"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.registry

Purpose:
    The set of skills A01 can run, and their declared readiness.

Design goals:
    - Only implemented skills registered; an empty folder is not a claim
    - Readiness stated per skill, so a caller knows what it is relying on
    - Lookup by name, iteration in a stable order
    - No skill constructed with I/O; construction is free

Notes:
    All nineteen skill folders now hold an implementation. Every skill is
    registered as ``LIMITED`` because each answers from what A01 stores
    today -- transfers, blocks, and labels -- and states what it cannot see.

    The original four (wallet_profile, whale_transfers, token_flow,
    exchange_flow) are bounded by the same constraints as before. The
    fifteen new skills are bounded by the data they need but A01 does not
    yet ingest: prices, consensus-layer state, contract bytecode, protocol
    adapters, and repository sensors. Each skill states its bound honestly
    and declines rather than guesses when the data is absent.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterator

from .base import Skill
from .bridge.analysis import BridgeSkill
from .cross_chain.analysis import CrossChainSkill
from .defi.analysis import DefiSkill
from .developer_activity.analysis import DeveloperActivitySkill
from .exchange_flow.flow import ExchangeFlowSkill
from .governance.analysis import GovernanceSkill
from .mining.analysis import MiningSkill
from .network_health.monitor import NetworkHealthSkill
from .nft.analysis import NftSkill
from .security.scanner import SecuritySkill
from .smart_contract.analysis import SmartContractSkill
from .smart_money.tracker import SmartMoneySkill
from .stablecoin.analysis import StablecoinSkill
from .staking.analysis import StakingSkill
from .token_flow.flow import TokenFlowSkill
from .token_unlock.analysis import TokenUnlockSkill
from .validator.analysis import ValidatorSkill
from .wallet_lookup.profile import WalletProfileSkill
from .whale_detection.transfers import WhaleTransferSkill

logger = logging.getLogger(__name__)


class Readiness(StrEnum):
    """How far a skill can be relied on."""

    #: Implemented and covered by tests against a fixture database.
    IMPLEMENTED = "implemented"
    #: Implemented, but bounded by a data source A01 does not yet have.
    LIMITED = "limited"
    #: Folder exists, no implementation. Never registered.
    PLANNED = "planned"


@dataclass(frozen=True, slots=True)
class SkillEntry:
    """A registered skill and what it can be trusted for."""

    skill: Skill
    readiness: Readiness
    #: What is missing, when readiness is LIMITED. Empty otherwise.
    bounded_by: str = ""

    @property
    def name(self) -> str:
        return self.skill.name

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.skill.name,
            "description": self.skill.description,
            "readiness": self.readiness.value,
            "bounded_by": self.bounded_by,
        }


def _entries() -> tuple[SkillEntry, ...]:
    """
    Skills with an implementation, in the order a composer should run them.

    Profile first: it establishes whether the window supports absence claims
    at all. Flow and detection next. Specialized skills last.
    """
    return (
        # -- original four --
        SkillEntry(WalletProfileSkill(), Readiness.LIMITED, bounded_by="no balance sensor, so materiality cannot be assessed"),
        SkillEntry(WhaleTransferSkill(), Readiness.LIMITED, bounded_by="no price feed, so USD floors are unavailable; this skill does not read the label ledger, so a transfer's counterparty type is still unresolved"),
        SkillEntry(TokenFlowSkill(), Readiness.LIMITED, bounded_by="no event-log decoding, so only native value is covered"),
        SkillEntry(ExchangeFlowSkill(), Readiness.LIMITED, bounded_by="attribution is only as good as the loaded label list, which is unverified and covers no token transfers"),
        # -- behavioral / label-dependent --
        SkillEntry(SmartMoneySkill(), Readiness.LIMITED, bounded_by="no price feed, so profitability is inferred from behavioral signals (first-mover timing, counterparty diversity) rather than P&L"),
        SkillEntry(StablecoinSkill(), Readiness.LIMITED, bounded_by="identification by hardcoded contract list; unlisted stablecoins are invisible; no peg-deviation data"),
        SkillEntry(BridgeSkill(), Readiness.LIMITED, bounded_by="attribution depends on loaded bridge labels; no bridge event registry or cross-chain correlation"),
        SkillEntry(MiningSkill(), Readiness.LIMITED, bounded_by="attribution depends on loaded mining_pool labels; native value only"),
        SkillEntry(SecuritySkill(), Readiness.LIMITED, bounded_by="no contract bytecode analysis; mixer detection depends on loaded labels; dust threshold is hardcoded"),
        # -- pattern-based --
        SkillEntry(SmartContractSkill(), Readiness.LIMITED, bounded_by="no ABI resolution or bytecode analysis; contract vs EOA distinction requires labels"),
        SkillEntry(NftSkill(), Readiness.LIMITED, bounded_by="no ERC-721/1155 event decoding; NFT detection is heuristic (value=1 in token transfers)"),
        SkillEntry(NetworkHealthSkill(), Readiness.LIMITED, bounded_by="no validator or mempool telemetry; block timing inferred from stored timestamps only"),
        SkillEntry(CrossChainSkill(), Readiness.LIMITED, bounded_by="same-address lookup only; no bridge event matching or cross-chain flow tracing"),
        SkillEntry(TokenUnlockSkill(), Readiness.LIMITED, bounded_by="no vesting contract state; periodic outflow detection is heuristic"),
        # -- consensus-layer dependent --
        SkillEntry(StakingSkill(), Readiness.LIMITED, bounded_by="no consensus-layer data; staking detection is heuristic (deposit contract interactions and 32 ETH transfers)"),
        SkillEntry(ValidatorSkill(), Readiness.LIMITED, bounded_by="no consensus-layer data; validator identification uses keyword matching on contract labels"),
        SkillEntry(GovernanceSkill(), Readiness.LIMITED, bounded_by="no governance event decoding; governance contract identification uses keyword matching on contract labels"),
        SkillEntry(DefiSkill(), Readiness.LIMITED, bounded_by="no protocol adapters; protocol identification requires contract labels"),
        SkillEntry(DeveloperActivitySkill(), Readiness.LIMITED, bounded_by="no repository sensors; only on-chain contract creation (to=null) is detectable"),
    )


PLANNED_SKILLS: dict[str, str] = {}


class SkillRegistry:
    """
    Lookup for the skills layer.

    Constructs its skills eagerly because construction performs no I/O -- a
    skill holds thresholds and nothing else, and the repository arrives per
    call. Lazy construction would buy nothing and hide a broken import until
    the first query.
    """

    def __init__(self, entries: tuple[SkillEntry, ...] | None = None) -> None:
        self._entries: dict[str, SkillEntry] = {}
        for entry in entries if entries is not None else _entries():
            self._entries[entry.name] = entry

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[SkillEntry]:
        return iter(self._entries.values())

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    # -- lookup ----------------------------------------------------------

    def get(self, name: str) -> Skill:
        """One skill by name, or a KeyError naming what is available."""
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(
                f"no skill named {name!r}; registered: {', '.join(sorted(self._entries))}"
            )
        return entry.skill

    def entry(self, name: str) -> SkillEntry:
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(f"no skill named {name!r}")
        return entry

    def names(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def register(self, entry: SkillEntry) -> None:
        """Install a skill, replacing any of the same name. The seam for tests."""
        self._entries[entry.name] = entry

    # -- reporting -------------------------------------------------------

    def catalog(self) -> tuple[dict[str, Any], ...]:
        """Every registered skill with its readiness, for `cli skills`."""
        return tuple(entry.as_dict() for entry in self._entries.values())

    def planned(self) -> tuple[dict[str, str], ...]:
        """Skills that are specified but unbuilt, with the blocking reason."""
        return tuple(
            {"name": name, "blocked_by": reason}
            for name, reason in sorted(PLANNED_SKILLS.items())
        )

    def health(self) -> dict[str, Any]:
        return {
            "implemented": len(self._entries),
            "planned": len(PLANNED_SKILLS),
            "skills": list(self.catalog()),
        }

    def __repr__(self) -> str:
        return f"SkillRegistry(implemented={len(self._entries)})"


def default_registry() -> SkillRegistry:
    """A registry over every implemented skill."""
    return SkillRegistry()


__all__ = [
    "PLANNED_SKILLS",
    "Readiness",
    "SkillEntry",
    "SkillRegistry",
    "default_registry",
]
