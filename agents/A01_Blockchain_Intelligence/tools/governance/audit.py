"""
Tools :: Governance :: Audit
============================

Immutable execution audit: every governance event lands in an append-only
log keyed by request_id with tool/user identity, policy decision,
approval evidence and result references.

Audit logs must never be modifiable by the executing tool.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["AuditEntry", "AuditStore"]


@dataclass
class AuditEntry:
    """One append-only audit record."""

    event: str
    request_id: str = ""
    tool_id: str = ""
    user_id: str = ""
    session_id: str = ""
    policy_version: str = ""
    decision: str = ""
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    prev_hash: str = ""
    hash: str = ""

    def finalize(self, prev_hash: str) -> "AuditEntry":
        """Compute the chained hash (content + prev hash)."""
        self.prev_hash = prev_hash
        body = (
            f"{self.entry_id}|{self.timestamp}|{self.event}|{self.request_id}|"
            f"{self.tool_id}|{self.user_id}|{self.decision}|{self.prev_hash}"
        ).encode("utf-8")
        self.hash = hashlib.sha256(body).hexdigest()
        return self

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "event": self.event,
            "request_id": self.request_id,
            "tool_id": self.tool_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "policy_version": self.policy_version,
            "decision": self.decision,
            "timestamp": self.timestamp,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
            "details": dict(self.details),
        }


class AuditStore:
    """Hash-chained, append-only audit store."""

    def __init__(self) -> None:
        self._entries: List[AuditEntry] = []

    def append(self, entry: AuditEntry) -> AuditEntry:
        prev = self._entries[-1].hash if self._entries else "0" * 64
        entry.finalize(prev)
        self._entries.append(entry)
        return entry

    def log(
        self,
        event: str,
        *,
        request_id: str = "",
        tool_id: str = "",
        user_id: str = "",
        session_id: str = "",
        policy_version: str = "",
        decision: str = "",
        **details: Any,
    ) -> AuditEntry:
        entry = AuditEntry(
            event=event,
            request_id=request_id,
            tool_id=tool_id,
            user_id=user_id,
            session_id=session_id,
            policy_version=policy_version,
            decision=decision,
            details=dict(details),
        )
        return self.append(entry)

    def entries(self, limit: int = 200) -> List[AuditEntry]:
        return list(self._entries[-max(1, int(limit)):])

    def by_request(self, request_id: str) -> List[AuditEntry]:
        return [entry for entry in self._entries if entry.request_id == request_id]

    def verify_chain(self) -> bool:
        """True when every hash chains correctly (tamper detection)."""
        previous = "0" * 64
        for entry in self._entries:
            if entry.prev_hash != previous or entry.hash != self._compute(entry):
                return False
            previous = entry.hash
        return True

    def _compute(self, entry: AuditEntry) -> str:
        body = (
            f"{entry.entry_id}|{entry.timestamp}|{entry.event}|{entry.request_id}|"
            f"{entry.tool_id}|{entry.user_id}|{entry.decision}|{entry.prev_hash}"
        ).encode("utf-8")
        return hashlib.sha256(body).hexdigest()

    def __len__(self) -> int:
        return len(self._entries)