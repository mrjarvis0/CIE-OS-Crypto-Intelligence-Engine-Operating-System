"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    skills.registry

Purpose:
    The set of skills A01 can run, and their declared readiness.

Design goals:
    - Only implemented skills registered; the eighteen folders are not a claim
    - Readiness stated per skill, so a caller knows what it is relying on
    - Lookup by name, iteration in a stable order
    - No skill constructed with I/O; construction is free

Notes:
    Fifteen of the nineteen skill folders hold nothing but a ``.gitkeep`` --
    counted, because the previous "fifteen of eighteen" here had drifted from
    the tree. They are a plan, and a registry that listed them would turn that
    plan into an advertised capability, which is exactly the failure
    ``identity/capabilities.md`` v2.0.0 was written to stop. Only skills with an
    implementation appear here.

    ``exchange_flow`` left that list once address labels existed to load. It is
    registered as ``LIMITED`` rather than ``IMPLEMENTED`` because its answer is
    only as good as the list behind it: an unverified community list attributes
    an address on somebody's say-so, and no exchange list is complete.

    ``smart_money`` is the notable absence. Tracking it requires knowing which
    addresses have been profitable, which needs token prices and entity labels;
    A01 ingests neither. A ranking built without them would be an ordering of
    addresses by activity wearing the name of an ordering by skill, and nothing
    in the output would show the difference. It stays unbuilt until there is a
    data source that can support it.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterator

from .base import Skill
from .exchange_flow.flow import ExchangeFlowSkill
from .token_flow.flow import TokenFlowSkill
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


#: Skills with an implementation, in the order a composer should run them.
#: Profile first: it establishes whether the window supports absence claims at
#: all, which the others report alongside their own answers.
def _entries() -> tuple[SkillEntry, ...]:
    return (
        SkillEntry(WalletProfileSkill(), Readiness.LIMITED, bounded_by="no balance sensor, so materiality cannot be assessed"),
        SkillEntry(WhaleTransferSkill(), Readiness.LIMITED, bounded_by="no price feed, so USD floors are unavailable; this skill does not read the label ledger, so a transfer's counterparty type is still unresolved"),
        SkillEntry(TokenFlowSkill(), Readiness.LIMITED, bounded_by="no event-log decoding, so only native value is covered"),
        SkillEntry(ExchangeFlowSkill(), Readiness.LIMITED, bounded_by="attribution is only as good as the loaded label list, which is unverified and covers no token transfers"),
    )


#: Skills named in ``skills/README.md`` with no implementation, and why. Listed
#: so the gap is documented rather than merely absent.
PLANNED_SKILLS: dict[str, str] = {
    "smart_money": "needs token prices and entity labels; A01 ingests neither",
    "stablecoin": "needs ERC-20 event decoding",
    "token_unlock": "needs vesting contract state",
    "staking": "needs consensus-layer data",
    "validator": "needs consensus-layer data",
    "governance": "needs governance contract event decoding",
    "bridge": "needs bridge event registry and cross-chain correlation",
    "defi": "needs protocol adapters",
    "nft": "needs ERC-721/1155 event decoding",
    "security": "needs contract bytecode analysis",
    "smart_contract": "needs ABI resolution and bytecode analysis",
    "network_health": "needs validator and mempool telemetry",
    "cross_chain": "needs two chains ingested plus bridge correlation",
    "developer_activity": "needs repository sensors",
    "mining": "needs pool attribution labels",
}


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
