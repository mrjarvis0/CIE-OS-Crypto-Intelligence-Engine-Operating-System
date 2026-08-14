"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.attribution.ownership

Purpose:
    Ownership attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Ownership:
    """
    A claim that an owner controls a subject.
    """

    owner: str
    owned: str
    basis: str
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "owned": self.owned,
            "basis": self.basis,
            "confidence": self.confidence,
        }


class OwnershipResolver:
    """
    Determines ownership from deployment and control signals.
    """

    def resolve(self, subject: dict[str, Any]) -> Ownership | None:
        """
        Attribute ownership of a contract to its deployer.
        """
        deployer = subject.get("deployer")
        address = subject.get("address")
        if not deployer or not address:
            return None
        return Ownership(
            owner=str(deployer),
            owned=str(address),
            basis="deployer",
            confidence=0.9,
        )
