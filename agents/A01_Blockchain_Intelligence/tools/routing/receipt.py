"""
Tools :: Routing :: Receipt
===========================

Creates explainable routing receipts. Every routing decision records
the selected target, rejected candidates, policy decisions, scores,
context summary and timestamp — for auditability and debugging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..utils.helpers import iso_now
from ..utils.ids import new_id

__all__ = ["RoutingReceipt", "ReceiptLog"]


@dataclass
class RoutingReceipt:
    """Auditable record of one routing decision."""

    request_id: str = field(default_factory=new_id)
    route_id: str = field(default_factory=new_id)
    selected_target: str = ""
    rejected_candidates: List[Dict[str, Any]] = field(default_factory=list)
    policy_decisions: List[Dict[str, Any]] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    context_summary: Dict[str, Any] = field(default_factory=dict)
    decision_score: float = 0.0
    latency_ms: float = 0.0
    cost_estimate: float = 0.0
    execution_status: str = "planned"
    created_at: str = field(default_factory=iso_now)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "route_id": self.route_id,
            "selected_target": self.selected_target,
            "rejected_candidates": list(self.rejected_candidates),
            "policy_decisions": list(self.policy_decisions),
            "scores": dict(self.scores),
            "context_summary": dict(self.context_summary),
            "decision_score": round(self.decision_score, 4),
            "latency_ms": round(self.latency_ms, 3),
            "cost_estimate": round(self.cost_estimate, 6),
            "execution_status": self.execution_status,
            "created_at": self.created_at,
        }


class ReceiptLog:
    """Append-only log of routing receipts."""

    def __init__(self, capacity: int = 1000) -> None:
        self.capacity = max(1, int(capacity))
        self._receipts: List[RoutingReceipt] = []

    def record(self, receipt: RoutingReceipt) -> RoutingReceipt:
        self._receipts.append(receipt)
        if len(self._receipts) > self.capacity:
            self._receipts = self._receipts[-self.capacity:]
        return receipt

    def latest(self, limit: int = 10) -> List[RoutingReceipt]:
        return list(self._receipts[-max(1, int(limit)):])

    def by_request(self, request_id: str) -> List[RoutingReceipt]:
        return [receipt for receipt in self._receipts if receipt.request_id == request_id]

    def __len__(self) -> int:
        return len(self._receipts)