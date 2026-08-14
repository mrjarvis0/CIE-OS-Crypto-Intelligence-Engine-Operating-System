"""
Tools :: Governance :: Ownership
================================

Ownership and accountability: every tool must have an owner.

Tracks tool owner, maintainer, business owner, security owner, approval
owner and contact information, with an immutable assignment history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

__all__ = ["Ownership", "OwnershipRegistry"]


@dataclass
class Ownership:
    """Accountability record for one tool."""

    tool_id: str
    owner: str = ""
    maintainer: str = ""
    business_owner: str = ""
    security_owner: str = ""
    approval_owner: str = ""
    contact: str = ""

    def __post_init__(self) -> None:
        if not self.owner and not self.maintainer:
            raise ValueError("a tool must have an owner or maintainer")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "owner": self.owner,
            "maintainer": self.maintainer,
            "business_owner": self.business_owner,
            "security_owner": self.security_owner,
            "approval_owner": self.approval_owner,
            "contact": self.contact,
        }


class OwnershipRegistry:
    """Registry of tool ownership records with history."""

    def __init__(self) -> None:
        self._records: Dict[str, Ownership] = {}
        self._history: Dict[str, List[Dict[str, Any]]] = {}

    def register(self, ownership: Ownership) -> Ownership:
        self._records[ownership.tool_id] = ownership
        self._history.setdefault(ownership.tool_id, []).append({"event": "register", "ownership": ownership.as_dict()})
        return ownership

    def get(self, tool_id: str) -> Optional[Ownership]:
        return self._records.get(tool_id)

    def require_owner(self, tool_id: str) -> Ownership:
        record = self.get(tool_id)
        if record is None:
            raise KeyError(f"no ownership record for tool {tool_id!r}")
        return record

    def transfer(self, tool_id: str, *, owner: str = "", maintainer: str = "") -> Ownership:
        record = self.require_owner(tool_id)
        if owner:
            record.owner = owner
        if maintainer:
            record.maintainer = maintainer
        self._history.setdefault(tool_id, []).append({"event": "transfer", "ownership": record.as_dict()})
        return record

    def history(self, tool_id: str) -> List[Dict[str, Any]]:
        return list(self._history.get(tool_id, []))

    def unowned(self) -> List[str]:
        return [tool_id for tool_id, record in self._records.items() if not record.owner and not record.maintainer]