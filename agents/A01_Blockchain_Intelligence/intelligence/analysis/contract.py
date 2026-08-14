"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.contract

Purpose:
    Contract analysis.

    Profiles a smart contract by verification status, upgradeability,
    and deployer linkage. An unverified or upgradeable contract carries
    elevated counterparty uncertainty.
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer


class ContractAnalyzer(BaseAnalyzer):
    """
    Produces a contract profile with risk-relevant signals.
    """

    name = "contract"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        contract_address = self._address(subject)
        verified = bool(self._get(subject, "verified", False))
        deployed_by = self._get(subject, "deployer")
        is_proxy = bool(self._get(subject, "proxy", False))
        renounced = bool(self._get(subject, "ownership_renounced", False))

        transparency = "verified" if verified else "unverified"
        upgrade_risk = "upgradeable" if is_proxy else "immutable"

        data = {
            "address": contract_address,
            "verified": verified,
            "deployer": deployed_by,
            "proxy": is_proxy,
            "ownership_renounced": renounced,
            "transparency": transparency,
            "upgrade_risk": upgrade_risk,
        }
        artifact = self._evidence(
            claim=(
                f"contract {contract_address} is {transparency} and "
                f"{upgrade_risk}, deployed by {deployed_by}"
            ),
            data=data,
            source_type="explorer",
            confidence=0.8,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"contract {contract_address}: {transparency}, {upgrade_risk}",
            confidence=0.8,
        )
