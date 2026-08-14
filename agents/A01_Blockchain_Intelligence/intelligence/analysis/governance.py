"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.governance

Purpose:
    Governance analysis.

    Assesses protocol governance health using voter participation and
    proposal activity, flagging low-participation quorum risk.
    Participation is a rate in [0, 1]; it is never fabricated from
    voter/proposal counts when no eligible-voter denominator exists.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer

# Participation below this rate is considered a quorum risk.
_LOW_PARTICIPATION = 0.1


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class GovernanceAnalyzer(BaseAnalyzer):
    """
    Produces a governance activity summary.
    """

    name = "governance"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        protocol = self._get(subject, "name")
        proposals = self._get(subject, "proposal_count", 0)
        voters = self._get(subject, "voter_count", 0)
        participation = self._get(subject, "voter_participation")
        eligible = self._get(subject, "eligible_voter_count")

        if participation is None and eligible:
            participation = _to_float(voters) / _to_float(eligible, 1.0)

        quorum_risk = participation is not None and 0.0 <= _to_float(participation) < _LOW_PARTICIPATION

        data = {
            "name": protocol,
            "proposal_count": proposals,
            "voter_count": voters,
            "voter_participation": participation,
            "quorum_risk": quorum_risk,
        }
        artifact = self._evidence(
            claim=f"governance for {protocol} has {proposals} proposals (quorum_risk={quorum_risk})",
            data=data,
            source_type="on_chain",
            confidence=0.5,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"governance {protocol}: quorum_risk={quorum_risk}",
            confidence=0.5,
        )
