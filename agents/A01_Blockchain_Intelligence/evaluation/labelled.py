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

Fine-tuning notes
-----------------
    The labeled window is designed for realistic coverage:

    * **Class imbalance**: negatives outnumber positives, matching deployment
      where most addresses are not whales, most wallets are not dormant, etc.
    * **Borderline cases**: values near each detector's decision boundary
      exercise threshold behaviour on both sides.
    * **Multi-signal subjects**: cases where multiple indicators fire, or
      where one indicator is suppressed by another (e.g. USD floor blocking
      a percentile-triggered whale).
    * **Varied parameters**: different dormancy bands, outlier magnitudes,
      flow directions, and suppressed transfer kinds.
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
#
# Population: 1100 values, log-spaced from 10 to ~989,588.
# The 99.9th percentile boundary sits between i=1098 (979,285) and
# i=1099 (989,588). A value must be strictly above 979,285 to reach
# percentile >= 99.9.
# =========================================================================

_WHALE_POP: list[float] = [10 ** (1 + (i / 1100) * 5) for i in range(1100)]
_WHALE_SUPPLY: float = 1e12


def whale_cases() -> list[LabelledCase]:
    """140 cases for DET-WHALE-01: 70 positive, 70 negative."""
    cases: list[LabelledCase] = []

    # -- 55 positive: clear whale transfers, well above population --------
    for i in range(55):
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

    # -- 5 positive: borderline, just above 99.9th percentile (980K-985K) -
    for i in range(5):
        value = 980_000 + i * 1_000
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x1100 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [{
                    "value": value,
                    "kind": "transfer",
                    "direction": "out",
                    "counterparty_type": "unlabelled",
                }],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=True,
            case_id=f"whale-pos-borderline-{i:03d}",
        ))

    # -- 5 positive: multi-transfer subjects (2-3 qualifying each) --------
    for i in range(5):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x1200 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [
                    {"value": 3_000_000 + i * 200_000, "kind": "transfer",
                     "direction": "out", "counterparty_type": "exchange"},
                    {"value": 2_000_000, "kind": "transfer",
                     "direction": "in", "counterparty_type": "unlabelled"},
                ],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=True,
            case_id=f"whale-pos-multi-{i:03d}",
        ))

    # -- 5 positive: with explicit usd_value above floor ------------------
    for i in range(5):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x1300 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [{
                    "value": 2_000_000,
                    "kind": "transfer",
                    "direction": "out",
                    "counterparty_type": "exchange",
                    "usd_value": 2_000_000 + i * 500_000,
                }],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=True,
            case_id=f"whale-pos-usd-{i:03d}",
        ))

    # -- 30 negative: small transfers, well below population ---------------
    for i in range(30):
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

    # -- 5 negative: borderline, just below 99.9th percentile (970K-977K) -
    for i in range(5):
        value = 970_000 + i * 1_500
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x2100 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [{
                    "value": value,
                    "kind": "transfer",
                    "direction": "out",
                    "counterparty_type": "exchange",
                }],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=False,
            case_id=f"whale-neg-borderline-{i:03d}",
        ))

    # -- 5 negative: USD floor blocks a percentile-qualifying transfer ----
    for i in range(5):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x2200 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [{
                    "value": 2_000_000,
                    "kind": "transfer",
                    "direction": "out",
                    "counterparty_type": "exchange",
                    "usd_value": 100_000 + i * 100_000,
                }],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=False,
            case_id=f"whale-neg-usd-floor-{i:03d}",
        ))

    # -- 10 negative: suppressed transfer kinds ----------------------------
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

    # -- 10 negative: no transfers at all ---------------------------------
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

    # -- 10 negative: medium transfers (95th-99th percentile, below 99.9) --
    for i in range(10):
        value = 500_000 + i * 30_000
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x4100 + i),
                "transfer_population": _WHALE_POP,
                "large_transfers": [{
                    "value": value,
                    "kind": "transfer",
                    "direction": "out" if i % 2 else "in",
                    "counterparty_type": "unlabelled",
                }],
                "circulating_supply": _WHALE_SUPPLY,
            },
            label=False,
            case_id=f"whale-neg-medium-{i:03d}",
        ))

    return cases


# =========================================================================
# DORMANT (DET-DORMANT-01)
#
# Dormancy bands: ancient (7y+), very_long (4y+), long (2y+), standard (1y+).
# Threshold: 365 days minimum.
# =========================================================================


def dormant_cases() -> list[LabelledCase]:
    """125 cases for DET-DORMANT-01: 60 positive, 65 negative."""
    cases: list[LabelledCase] = []

    # -- 10 positive: ancient dormancy (7+ years, > 2555 days) ------------
    for i in range(10):
        dormancy = 2600 + i * 100
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x5000 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=dormancy)
                ).isoformat(),
                "balance": 50_000.0 + i * 5_000,
                "balance_percentile_rank": 99.9,
                "reactivated": True,
                "movement_context": "",
            },
            label=True,
            case_id=f"dormant-pos-ancient-{i:03d}",
        ))

    # -- 15 positive: very long dormancy (4-7 years) ----------------------
    for i in range(15):
        dormancy = 1500 + i * 70
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x5100 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=dormancy)
                ).isoformat(),
                "balance": 10_000.0 + i * 1_000,
                "balance_percentile_rank": 99.7,
                "reactivated": True,
                "movement_context": "",
            },
            label=True,
            case_id=f"dormant-pos-vlong-{i:03d}",
        ))

    # -- 20 positive: long dormancy (2-4 years) ---------------------------
    for i in range(20):
        dormancy = 750 + i * 35
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x5200 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=dormancy)
                ).isoformat(),
                "balance": 2_000.0 + i * 200,
                "balance_percentile_rank": 99.5,
                "reactivated": True,
                "movement_context": "",
            },
            label=True,
            case_id=f"dormant-pos-long-{i:03d}",
        ))

    # -- 15 positive: standard dormancy (1-2 years) -----------------------
    for i in range(15):
        dormancy = 380 + i * 20
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x5300 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=dormancy)
                ).isoformat(),
                "balance": 1_000.0 + i * 100,
                "balance_percentile_rank": 99.2,
                "reactivated": True,
                "movement_context": "",
            },
            label=True,
            case_id=f"dormant-pos-standard-{i:03d}",
        ))

    # -- 15 negative: not dormant enough (30-310 days) --------------------
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

    # -- 5 negative: borderline dormancy (350-364 days, just under 365) ---
    for i in range(5):
        dormancy = 350 + i * 3
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x6100 + i),
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
            case_id=f"dormant-neg-borderline-{i:03d}",
        ))

    # -- 10 negative: immaterial balance ----------------------------------
    for i in range(10):
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

    # -- 5 negative: low percentile rank (below 99.0 threshold) -----------
    for i in range(5):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0x7100 + i),
                "as_of": _AS_OF.isoformat(),
                "last_outbound_at": (
                    _AS_OF - timedelta(days=500)
                ).isoformat(),
                "balance": 100.0,
                "balance_percentile_rank": 90.0 + i * 1.5,
                "reactivated": True,
                "movement_context": "",
            },
            label=False,
            case_id=f"dormant-neg-lowpct-{i:03d}",
        ))

    # -- 15 negative: not reactivated -------------------------------------
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

    # -- 15 negative: benign movement context -----------------------------
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
#
# The detector uses modified z-scores in log10 space.
# OUTLIER_Z = 3.5, MIN_POPULATION = 20, PATTERN_OUTLIERS = 3.
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


def _multi_outlier_population(
    count: int, base: float = 100.0, spread: float = 10.0,
    n_outliers: int = 3, outlier: float = 1e7,
) -> list[float]:
    """Deterministic population with multiple outliers."""
    normal = _tight_population(count - n_outliers, base, spread)
    return normal + [outlier * (1.0 + k * 0.5) for k in range(n_outliers)]


def anomaly_cases() -> list[LabelledCase]:
    """135 cases for DET-ANOMALY-01: 60 positive, 75 negative."""
    cases: list[LabelledCase] = []

    # -- 45 positive: single outlier, varying magnitude -------------------
    for i in range(45):
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

    # -- 10 positive: multiple outliers (PATTERN_OUTLIERS coverage) -------
    for i in range(10):
        n_out = 3 + (i % 3)
        cases.append(LabelledCase(
            subject={
                "address": _addr(0xA100 + i),
                "transfer_population": _multi_outlier_population(
                    count=35,
                    base=100 + i * 5,
                    n_outliers=n_out,
                    outlier=10.0 ** (6 + i % 3),
                ),
                "absence_meaningful": True,
            },
            label=True,
            case_id=f"anomaly-pos-multi-{i:03d}",
        ))

    # -- 5 positive: larger populations with outliers ---------------------
    for i in range(5):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0xA200 + i),
                "transfer_population": _outlier_population(
                    count=60,
                    base=200 + i * 20,
                    spread=15.0,
                    outlier=10.0 ** 8,
                ),
                "absence_meaningful": True,
            },
            label=True,
            case_id=f"anomaly-pos-large-pop-{i:03d}",
        ))

    # -- 45 negative: normal populations, no outliers ---------------------
    for i in range(45):
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

    # -- 15 negative: small populations (below MIN_POPULATION of 20) ------
    for i in range(15):
        size = 3 + i
        cases.append(LabelledCase(
            subject={
                "address": _addr(0xB100 + i),
                "transfer_population": _tight_population(
                    count=size, base=100 + i * 10, spread=30.0,
                ),
                "absence_meaningful": True,
            },
            label=False,
            case_id=f"anomaly-neg-small-{i:03d}",
        ))

    # -- 10 negative: uniform populations (MAD = 0, z-scores undefined) ---
    for i in range(10):
        value = 100.0 + i * 50
        cases.append(LabelledCase(
            subject={
                "address": _addr(0xB200 + i),
                "transfer_population": [value] * 25,
                "absence_meaningful": True,
            },
            label=False,
            case_id=f"anomaly-neg-uniform-{i:03d}",
        ))

    # -- 5 negative: absence_meaningful=False with normal population ------
    for i in range(5):
        cases.append(LabelledCase(
            subject={
                "address": _addr(0xB300 + i),
                "transfer_population": _tight_population(
                    count=30, base=100 + i * 5, spread=15.0,
                ),
                "absence_meaningful": False,
            },
            label=False,
            case_id=f"anomaly-neg-no-absence-{i:03d}",
        ))

    return cases


# =========================================================================
# EXCHANGE FLOW (DET-EXCHANGE-01)
#
# DIRECTIONAL_RATIO = 0.20, MIN_ATTRIBUTED = 10.
# imbalance = |inflow - outflow| / (inflow + outflow).
# =========================================================================


def _exchange_flow_subject(
    index: int,
    *,
    inflow: int,
    outflow: int,
    attributed: int = 15,
    label_confidence: float = 0.5,
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
            "label_confidence": label_confidence,
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
    """135 cases for DET-EXCHANGE-01: 65 positive, 70 negative."""
    cases: list[LabelledCase] = []

    # -- 25 positive: clear net inflow ------------------------------------
    for i in range(25):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(
                0xC000 + i,
                inflow=1000 + i * 100,
                outflow=100 + i * 10,
            ),
            label=True,
            case_id=f"exflow-pos-inflow-{i:03d}",
        ))

    # -- 25 positive: clear net outflow -----------------------------------
    for i in range(25):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(
                0xD000 + i,
                inflow=100 + i * 10,
                outflow=1000 + i * 100,
            ),
            label=True,
            case_id=f"exflow-pos-outflow-{i:03d}",
        ))

    # -- 5 positive: borderline directional (ratio 0.22-0.26) ------------
    _border_dir = [(610, 390), (620, 380), (630, 370), (390, 610), (380, 620)]
    for i, (inf, outf) in enumerate(_border_dir):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(0xD100 + i, inflow=inf, outflow=outf),
            label=True,
            case_id=f"exflow-pos-borderline-{i:03d}",
        ))

    # -- 5 positive: with higher attributed count -------------------------
    for i in range(5):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(
                0xD200 + i,
                inflow=5000 + i * 500,
                outflow=500,
                attributed=30 + i * 10,
            ),
            label=True,
            case_id=f"exflow-pos-high-attr-{i:03d}",
        ))

    # -- 5 positive: with varying label confidence ------------------------
    for i in range(5):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(
                0xD300 + i,
                inflow=2000,
                outflow=200,
                label_confidence=0.3 + i * 0.1,
            ),
            label=True,
            case_id=f"exflow-pos-conf-{i:03d}",
        ))

    # -- 25 negative: balanced flow (ratio ~0.05) -------------------------
    for i in range(25):
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

    # -- 5 negative: borderline balanced (ratio 0.14-0.18, below 0.20) ----
    _border_bal = [(590, 410), (580, 420), (570, 430), (410, 590), (420, 580)]
    for i, (inf, outf) in enumerate(_border_bal):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(0xE100 + i, inflow=inf, outflow=outf),
            label=False,
            case_id=f"exflow-neg-borderline-{i:03d}",
        ))

    # -- 25 negative: insufficient attributed transfers (< 10) ------------
    for i in range(25):
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

    # -- 5 negative: zero gross (attributed but no native value) ----------
    for i in range(5):
        cases.append(LabelledCase(
            subject=_exchange_flow_subject(
                0xF100 + i,
                inflow=0,
                outflow=0,
                attributed=15,
            ),
            label=False,
            case_id=f"exflow-neg-zero-gross-{i:03d}",
        ))

    # -- 10 negative: no exchange_flow key in subject ---------------------
    for i in range(10):
        cases.append(LabelledCase(
            subject={"address": _addr(0xF200 + i)},
            label=False,
            case_id=f"exflow-neg-missing-{i:03d}",
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
