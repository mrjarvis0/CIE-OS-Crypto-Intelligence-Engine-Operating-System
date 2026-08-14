"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.correlation.exchange_linking

Purpose:
    Link wallets to known exchange addresses.
"""

from __future__ import annotations

from typing import Any

from .correlator import Correlation


class ExchangeLinker:
    """
    Links a wallet to an exchange when transactions involve it.
    """

    def __init__(self, exchanges: dict[str, str] | None = None) -> None:
        self._exchanges = dict(exchanges or {})

    def link(self, subjects: list[dict[str, Any]]) -> list[Correlation]:
        correlations: list[Correlation] = []
        for subject in subjects:
            address = subject.get("address")
            for counter in subject.get("counterparties", []):
                for name, ex_address in self._exchanges.items():
                    if counter == ex_address and address:
                        correlations.append(
                            Correlation(
                                left=str(address),
                                right=str(ex_address),
                                relation=f"exchange_{name}",
                                confidence=0.85,
                            )
                        )
        return correlations
