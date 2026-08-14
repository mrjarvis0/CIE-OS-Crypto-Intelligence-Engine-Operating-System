"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.analysis.transaction

Purpose:
    Transaction analysis.

    Profiles an individual transaction: value, method, counterparties,
    and structural risk flags (self-send, unknown method, anomaly).
"""

from __future__ import annotations

from typing import Any

from .base import AnalyzerResult, BaseAnalyzer


class TransactionAnalyzer(BaseAnalyzer):
    """
    Produces a transaction-level summary with structural risk flags.
    """

    name = "transaction"

    def analyze(self, subject: dict[str, Any], **_: Any) -> AnalyzerResult:
        tx_hash = self._get(subject, "hash")
        value = self._get(subject, "value", 0)
        method = self._get(subject, "method")
        from_addr = self._address(subject, "from")
        to_addr = self._address(subject, "to")
        status = self._get(subject, "status", "success")

        self_send = bool(from_addr and to_addr and from_addr == to_addr)
        unresolved_method = method is None or str(method) == "0x" or str(method) == "unknown"

        data = {
            "hash": tx_hash,
            "value": value,
            "method": method,
            "from": from_addr,
            "to": to_addr,
            "status": status,
            "self_send": self_send,
            "unresolved_method": unresolved_method,
        }
        artifact = self._evidence(
            claim=f"transaction {tx_hash} of value {value} {method or 'unresolved'}-method",
            data=data,
            source_type="explorer",
            confidence=0.8,
        )
        return self._result(
            data=data,
            evidence=[artifact],
            summary=f"tx {tx_hash}: value={value}, method={method or 'unresolved'}",
            confidence=0.8,
        )
