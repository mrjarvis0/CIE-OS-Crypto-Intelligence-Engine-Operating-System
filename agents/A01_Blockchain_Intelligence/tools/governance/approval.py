"""
Tools :: Governance :: Approval
===============================

Human-in-the-loop approval system: single and multi-level approvals,
risk-based thresholds, emergency overrides, time limits and history.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = ["ApprovalRequest", "ApprovalDecision", "ApprovalManager"]

_RISK_LEVELS = {"low", "medium", "high", "critical"}
_LEVEL_LIMITS = {"low": 1, "medium": 1, "high": 2, "critical": 2}


@dataclass
class ApprovalRequest:
    """A pending approval gate."""

    action: str
    risk: str = "medium"
    required_levels: int = 1
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    approvers: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "risk": self.risk,
            "required_levels": self.required_levels,
            "approvers": list(self.approvers),
            "expired": self.expired,
        }


@dataclass
class ApprovalDecision:
    """Result of an approval attempt."""

    request: ApprovalRequest
    approved: bool
    level: int = 0
    approver: str = ""
    reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request.request_id,
            "approved": self.approved,
            "level": self.level,
            "approver": self.approver,
            "reason": self.reason,
            "action": self.request.action,
        }


class ApprovalManager:
    """Approval workflow manager with history."""

    def __init__(self) -> None:
        self._pending: Dict[str, ApprovalRequest] = {}
        self._history: List[ApprovalDecision] = []
        self._risk_limit: Dict[str, int] = dict(_LEVEL_LIMITS)
        self._default_approvers: List[str] = []

    def set_default_approvers(self, approvers: Sequence[str]) -> None:
        self._default_approvers = list(approvers)

    def set_risk_limit(self, risk: str, levels: int) -> None:
        if risk not in _RISK_LEVELS:
            raise ValueError(f"unknown risk level {risk!r}")
        self._risk_limit[risk] = max(1, int(levels))

    def request(self, action: str, *, risk: str = "medium", timeout_seconds: Optional[float] = None, context: Optional[Mapping[str, Any]] = None) -> ApprovalRequest:
        if risk not in _RISK_LEVELS:
            raise ValueError(f"unknown risk level {risk!r}")
        required = self._risk_limit.get(risk, 1)
        approval = ApprovalRequest(
            action=action,
            risk=risk,
            required_levels=required,
            approvers=list(self._default_approvers),
            expires_at=(time.time() + timeout_seconds) if timeout_seconds else None,
            context=dict(context or {}),
        )
        self._pending[approval.request_id] = approval
        return approval

    def decide(self, request_id: str, *, approver: str, approve: bool, reason: str = "") -> ApprovalDecision:
        request = self._pending.get(request_id)
        if request is None:
            raise KeyError(f"unknown approval request {request_id!r}")
        if request.expired:
            decision = ApprovalDecision(request, approved=False, reason="expired")
            self._history.append(decision)
            return decision
        level = 1
        if approver in request.approvers:
            level = min(request.required_levels, request.approvers.index(approver) + 1)
        if not approve:
            decision = ApprovalDecision(request, approved=False, level=level, approver=approver, reason=reason or "denied")
            self._pending.pop(request_id, None)
            self._history.append(decision)
            return decision
        decision = ApprovalDecision(request, approved=True, level=level, approver=approver, reason=reason or "approved")
        if level >= request.required_levels:
            self._pending.pop(request_id, None)
        self._history.append(decision)
        return decision

    def approve(self, request_id: str, *, approver: str, reason: str = "") -> ApprovalDecision:
        return self.decide(request_id, approver=approver, approve=True, reason=reason)

    def deny(self, request_id: str, *, approver: str, reason: str = "") -> ApprovalDecision:
        return self.decide(request_id, approver=approver, approve=False, reason=reason)

    def emergency_override(self, request_id: str, *, approver: str, reason: str) -> ApprovalDecision:
        request = self._pending.get(request_id)
        if request is None:
            raise KeyError(f"unknown approval request {request_id!r}")
        decision = ApprovalDecision(request, approved=True, level=request.required_levels, approver=approver, reason=f"EMERGENCY: {reason}")
        self._pending.pop(request_id, None)
        self._history.append(decision)
        return decision

    def status(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._pending.get(request_id)

    def history(self, limit: int = 100) -> List[ApprovalDecision]:
        return list(self._history[-max(1, int(limit)):])