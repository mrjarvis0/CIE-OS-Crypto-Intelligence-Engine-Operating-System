"""
Tools :: Governance Layer
=========================

The trust, compliance, policy and control plane of the Tools subsystem.

Governance never executes tools: it verifies whether execution is
permitted before it begins (policy -> approval -> authorization) and
validates the resulting evidence afterwards (audit -> compliance ->
verification).

Modules: ownership, trust, policy, approval, signing, provenance, audit,
compliance, verification. A :class:`Governor` facade wires the common
gate into one call.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Mapping, Optional

__all__ = [
    "GovernanceError",
    "Ownership",
    "OwnershipRegistry",
    "TrustScore",
    "TrustRegistry",
    "classify_risk",
    "PolicyDecision",
    "PolicyRule",
    "PolicyEngine",
    "ApprovalRequest",
    "ApprovalDecision",
    "ApprovalManager",
    "SigningKey",
    "sign_bytes",
    "verify_bytes",
    "sign_payload",
    "verify_payload",
    "integrity_digest",
    "ProvenanceRecord",
    "ProvenanceTracker",
    "AuditEntry",
    "AuditStore",
    "ComplianceRequirement",
    "ComplianceCheck",
    "ComplianceReport",
    "ComplianceEngine",
    "VerificationResult",
    "Verifier",
    "Governor",
]

logger = logging.getLogger(__name__)


class GovernanceError(Exception):
    """Base class for every error raised by the governance layer."""


from .ownership import Ownership, OwnershipRegistry  # noqa: E402
from .trust import TrustScore, TrustRegistry, classify_risk  # noqa: E402
from .policy import PolicyDecision, PolicyRule, PolicyEngine  # noqa: E402
from .approval import ApprovalRequest, ApprovalDecision, ApprovalManager  # noqa: E402
from .signing import SigningKey, sign_bytes, verify_bytes, sign_payload, verify_payload, integrity_digest  # noqa: E402
from .provenance import ProvenanceRecord, ProvenanceTracker  # noqa: E402
from .audit import AuditEntry, AuditStore  # noqa: E402
from .compliance import ComplianceRequirement, ComplianceCheck, ComplianceReport, ComplianceEngine  # noqa: E402
from .verification import VerificationResult, Verifier  # noqa: E402


class Governor:
    """Facade: pre-execution authorization gate and post-execution evidence gate."""

    def __init__(
        self,
        *,
        policy: Optional[PolicyEngine] = None,
        approvals: Optional[ApprovalManager] = None,
        audit: Optional[AuditStore] = None,
        compliance: Optional[ComplianceEngine] = None,
        verifier: Optional[Verifier] = None,
    ) -> None:
        self.policy = policy if policy is not None else PolicyEngine()
        self.approvals = approvals if approvals is not None else ApprovalManager()
        self.audit = audit if audit is not None else AuditStore()
        self.compliance = compliance if compliance is not None else ComplianceEngine()
        self.verifier = verifier if verifier is not None else Verifier()

    # -- pre-execution ---------------------------------------------------------- #

    def authorize(self, context: Mapping[str, Any]) -> bool:
        """Policy gate; every decision is audited."""
        decision = self.policy.evaluate(context)
        self.audit.log(
            "policy",
            request_id=context.get("request_id", ""),
            tool_id=context.get("tool_id", ""),
            user_id=context.get("user_id", ""),
            policy_version=str(context.get("policy_version", "")),
            decision=decision.verdict,
            rule=decision.rule,
        )
        return decision.allowed

    def require_approval(self, action: str, *, risk: str = "medium", context: Optional[Mapping[str, Any]] = None) -> ApprovalRequest:
        return self.approvals.request(action, risk=risk, context=context)

    # -- post-execution ---------------------------------------------------------- #

    def record_evidence(self, *, request_id: str, tool_id: str, user_id: str = "", **details: Any) -> AuditEntry:
        return self.audit.log("evidence", request_id=request_id, tool_id=tool_id, user_id=user_id, **details)

    def compliance_report(self, context: Mapping[str, Any]) -> ComplianceReport:
        report = self.compliance.evaluate(context)
        self.audit.log("compliance", request_id=context.get("request_id", ""), decision="pass" if report.passed else "fail", pass_rate=report.pass_rate)
        return report

    def final_verification(self, context: Mapping[str, Any]) -> VerificationResult:
        result = self.verifier.verify(context)
        self.audit.log("verification", request_id=context.get("request_id", ""), decision="pass" if result.passed else "fail", checks=result.checks)
        return result