"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.correlation.wallet_linking

Purpose:
    Link wallets that share transactions.

    Implements the standard on-chain clustering heuristics: co-spend
    (multiple addresses funding one output/recipient in the same
    transaction), multiple-input-heuristic (MIH - inputs to a single
    transaction are presumed to share an operator), and counterparty
    interaction. Confidence reflects the strength of the heuristic;
    counterparty interaction is the weakest signal and is therefore
    scored lowest.
"""

from __future__ import annotations

from typing import Any

from .correlator import Correlation


class WalletLinker:
    """
    Detects wallet-to-wallet relationships via shared transactions.
    """

    def __init__(
        self,
        co_spend_confidence: float = 0.8,
        mih_confidence: float = 0.7,
        counterparty_confidence: float = 0.6,
    ) -> None:
        self._co_spend_confidence = co_spend_confidence
        self._mih_confidence = mih_confidence
        self._counterparty_confidence = counterparty_confidence

    def link(self, subjects: list[dict[str, Any]]) -> list[Correlation]:
        correlations: list[Correlation] = []
        seen: set[tuple[str, str, str]] = set()

        for subject in subjects:
            address = subject.get("address")
            if not address:
                continue

            # Counterparty interaction (weakest, largest link surface).
            for counter in subject.get("counterparties", []):
                if not counter or str(counter) == str(address):
                    continue
                correlations.extend(
                    self._emit(
                        seen,
                        str(address),
                        str(counter),
                        "counterparty",
                        self._counterparty_confidence,
                        ["tx:counterparty"],
                    )
                )

            # Co-spend / multiple-input heuristic (stronger).
            for tx_inputs in subject.get("co_spenders", []):
                for co in tx_inputs:
                    if not co or str(co) == str(address):
                        continue
                    correlations.extend(
                        self._emit(
                            seen,
                            str(address),
                            str(co),
                            "co_spend",
                            self._co_spend_confidence,
                            ["tx:shared_input"],
                        )
                    )

            # MIH: inputs to a single transaction share a likely operator.
            for mih_group in subject.get("mih_groups", []):
                group = [
                    str(a)
                    for a in mih_group
                    if a is not None and str(a) != str(address)
                ]
                for other in group:
                    correlations.extend(
                        self._emit(
                            seen,
                            str(address),
                            other,
                            "mih",
                            self._mih_confidence,
                            ["tx:multi_input"],
                        )
                    )

        return correlations

    def _emit(
        self,
        seen: set[tuple[str, str, str]],
        left: str,
        right: str,
        relation: str,
        confidence: float,
        evidence_refs: list[str],
    ) -> list[Correlation]:
        pair = tuple(sorted((left, right)))
        key = (pair[0], pair[1], relation)
        if key in seen:
            return []
        seen.add(key)
        return [
            Correlation(
                left=pair[0],
                right=pair[1],
                relation=relation,
                confidence=confidence,
                evidence_refs=evidence_refs,
            )
        ]
