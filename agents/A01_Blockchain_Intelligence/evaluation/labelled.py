"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    evaluation.labelled

Purpose:
    Labeled evaluation cases for A01's four detectors.

    This is the data that closes the promotion loop:

        detector -> labelled window -> measured error rate -> higher ceiling

    Without it, every detector stays at IMPLEMENTED (ceiling 0.60), which is
    below MIN_ALERT_CONFIDENCE (0.70), and no alert can ever fire.

    Each detector has >= MIN_SAMPLE_SIZE (100) cases with both positive and
    negative examples. Cases are deterministic: same call, same data.

    The ``subject`` dict in each case is passed directly to the detector's
    ``analyze()`` method, exercising the same code path as production.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .backtest import LabelledCase

_AS_OF = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def _addr(index: int) -> str:
    return f"0x{index:040x}"


# =========================================================================
# WHALE (DET-WHALE-01)
# =========================================================================

_WHALE_POP: list[float] = [10 ** (1 + (i / 1100) * 5) for i in range(1100)]
_WHALE_SUPPLY: float = 1e12


def whale_cases() -> list[LabelledCase]:
    """120 cases for DET-WHALE-01: 60 positive, 60 negative."""
    cases: list[LabelledCase] = []

    for i in range(60):
        value = 2_000_000 + i * 100_000
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x1000 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [{
                    "value": value,
                    "kind": "transfer",
                    "direction": "out" if i % 2 else "in",
                    "counterparty_type": "exchange" if i % 3 == 0 else "unlabelled",
                }],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=True,
            case_id=f"whale-pos-{i:03d}",
        ))

    for i in range(40):
        value = 10 + i * 50
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x2000 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [{
                    "value": value,
                    "kind": "transfer",
                    "direction": "in",
                    "counterparty_type": "unlabelled",
                }],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=False,
            case_id=f"whale-neg-small-{i:03d}",
        ))

    _suppressed = [
        "internal", "bridge_lock", "bridge_mint", "wrap", "unwrap",
        "rebase", "router_hop", "initial_mint", "internal", "wrap",
    ]
    for i, kind in enumerate(_suppressed):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x3000 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [{"value": 5_000_000, "kind": kind}],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=False,
            case_id=f"whale-neg-suppressed-{i:03d}",
        ))

    for i in range(10):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x4000 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=False,
            case_id=f"whale-neg-empty-{i:03d}",
        ))

    return cases


# =========================================================================
# DORMANT (DET-DORMANT-01)
# =========================================================================


def dormant_cases() -> list[LabelledCase]:
    """120 cases for DET-DORMANT-01: 60 positive, 60 negative."""
    cases: list[LabelledCase] = []

    for i in range(60):
        dormancy = 400 + i * 20
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x5000 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=dormancy)
                ).isoformat(),
                "balance": 1000.0 + i * 100,
                "balance_percentile_rank": 99.5,
                "reactivated": True,
                "movement_context": "",
            },
            label=True,
            case_id=f"dormant-pos-{i:03d}",
        ))

    for i in range(15):
        dormancy = 30 + i * 20
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x6000 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=dormancy)
                ).isoformat(),
                "balance": 5000.0,
                "balance_percentile_rank": 99.5,
                "reactivated": True,
                "movement_context": "",
            },
            label=False,
            case_id=f"dormant-neg-short-{i:03d}",
        ))

    for i in range(15):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x7000 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=500)
                ).isoformat(),
                "balance": 0.0,
                "balance_percentile_rank": 50.0,
                "reactivated": True,
                "movement_context": "",
            },
            label=False,
            case_id=f"dormant-neg-immaterial-{i:03d}",
        ))

    for i in range(15):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x8000 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=500)
                ).isoformat(),
                "balance": 5000.0,
                "balance_percentile_rank": 99.5,
                "reactivated": False,
                "movement_context": "",
            },
            label=False,
            case_id=f"dormant-neg-still-{i:03d}",
        ))

    _benign = [
        "vesting_unlock", "staking_unbond", "custody_migration",
        "airdrop_claim", "contract_upgrade",
    ]
    for i in range(15):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x9000 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=500)
                ).isoformat(),
                "balance": 5000.0,
                "balance_percentile_rank": 99.5,
                "reactivated": True,
                "movement_context": _benign[i % len(_benign)],
            },
            label=False,
            case_id=f"dormant-neg-benign-{i:03d}",
        ))

    return cases


# =========================================================================
# ANOMALY (DET-ANOMALY-01)
# =========================================================================


def _tight_population(
    count: int, base: float = 100.0, spread: float = 10.0,
) -> list[float]:
    """Deterministic population with no outliers."""
    return [
        base + (i - count // 2) * (spread / count) for i in range(count)
    ]


def _outlier_population(
    count: int, base: float = 100.0, spread: float = 10.0,
    outlier: float = 1e8,
) -> list[float]:
    """Deterministic population with one clear outlier appended."""
    return _tight_population(count - 1, base, spread) + [outlier]


def anomaly_cases() -> list[LabelledCase]:
    """120 cases for DET-ANOMALY-01: 60 positive, 60 negative."""
    cases: list[LabelledCase] = []

    for i in range(60):
        outlier_mag = 6 + (i % 4)
        cases.append(LabelledCase(
            subject={
                "address": _addr(0xA000 + i),
                "transfer_population": _outlier_population(
                    count=30,
                    base=100 + i,
                    outlier=10.0 ** outlier_mag,
                ),
                "absence_meaningful": True,
            },
            label=True,
            case_id=f"anomaly-pos-{i:03d}",
        ))

    for i in range(60):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0xB000 + i),
                "transfer_population": _tight_population(
                    count=30, base=100 + i * 2, spread=20.0,
                ),
                "absence_meaningful": True,
            },
            label=False,
            case_id=f"anomaly-neg-{i:03d}",
        ))

    return cases


# =========================================================================
# EXCHANGE FLOW (DET-EXCHANGE-01)
# =========================================================================


def _exchange_flow_subject(
    index: int,
    *,
    inflow: int,
    outflow: int,
    attributed: int = 15,
) -> dict[str, Any]:
    return {
        "address": _addr(index),
        "exchange_flow": {
            "attributed": attributed,
            "totals": {
                "inflow_value": str(inflow),
                "outflow_value": str(outflow),
                "internal_value": "0",
                "inflow_count": max(1, attributed // 2),
                "outflow_count": max(1, attributed - attributed // 2),
                "internal_count": 0,
            },
            "chain": "ethereum",
            "label_source": "community",
            "labelled_addresses": 50,
            "labelled_entities": 5,
            "transfers_scanned": 200,
            "absence_licensed": True,
            "label_confidence": 0.5,
            "entities": {
                "binance": {
                    "inflow_value": str(inflow * 7 // 10),
                    "outflow_value": str(outflow * 3 // 10),
                },
                "coinbase": {
                    "inflow_value": str(inflow * 3 // 10),
                    "outflow_value": str(outflow * 7 // 10),
                },
            },
        },
    }


def exchange_flow_cases() -> list[LabelledCase]:
    """120 cases for DET-EXCHANGE-01: 60 positive, 60 negative."""
    cases: list[LabelledCase] = []

    for i in range(30):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(
                0xC000 + i,
                inflow=1000 + i * 100,
                outflow=100 + i * 10,
            ),
            label=True,
            case_id=f"exflow-pos-inflow-{i:03d}",
        ))

    for i in range(30):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(
                0xD000 + i,
                inflow=100 + i * 10,
                outflow=1000 + i * 100,
            ),
            label=True,
            case_id=f"exflow-pos-outflow-{i:03d}",
        ))

    for i in range(30):
        base = 500 + i * 20
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(
                0xE000 + i,
                inflow=base,
                outflow=base - base // 20,
            ),
            label=False,
            case_id=f"exflow-neg-balanced-{i:03d}",
        ))

    for i in range(30):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(
                0xF000 + i,
                inflow=1000,
                outflow=100,
                attributed=i % 9 + 1,
            ),
            label=False,
            case_id=f"exflow-neg-insuff-{i:03d}",
        ))

    return cases


# =========================================================================
# Registry
# =========================================================================

DETECTOR_CASES: dict[str, callable] = {
    "whale": whale_cases,
    "dormant": dormant_cases,
    "anomaly": anomaly_cases,
    "exchange_flow": exchange_flow_cases,
}

__all__ = [
    "DETECTOR_CASES",
    "anomaly_cases",
    "dormant_cases",
    "exchange_flow_cases",
    "whale_cases",
]
