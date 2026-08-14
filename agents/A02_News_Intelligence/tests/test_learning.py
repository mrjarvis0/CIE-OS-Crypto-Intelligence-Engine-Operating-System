"""
CIE-OS
A02 News Intelligence Agent

Phase 5 tests — outcome learning, calibration, backtest metrics, drift (offline).
Run directly:
    python agents/A02_News_Intelligence/tests/test_learning.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agents.A02_News_Intelligence.core.storage import Storage
from agents.A02_News_Intelligence.intelligence.learning import (
    calibration,
    drift_report,
    metrics,
    resolved_events,
    truth_binary,
    verification_report,
)

PASS = 0
FAIL = 0


def check(label: str, ok: bool) -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}")


def event(
    predicted_direction: str = "up",
    actual_direction: str = "up",
    probability: float = 0.8,
    predicted_mean: float = 1.0,
    actual_return: float = 1.5,
    status: str = "confirmed_true",
    truth_outcome: str | None = "true",
) -> dict:
    return {
        "predicted_direction": predicted_direction,
        "actual_direction": actual_direction,
        "predicted_probability": probability,
        "predicted_mean_pct": predicted_mean,
        "actual_return": actual_return,
        "epistemic_status": status,
        "truth_outcome": truth_outcome,
    }


def test_resolved_events_filter() -> None:
    rows = [
        event(),
        {"predicted_direction": "up", "actual_direction": None},
        {"predicted_direction": None, "actual_direction": "down"},
        {},
    ]
    check("resolved_events keeps only matched pairs", len(resolved_events(rows)) == 1)


def test_truth_binary() -> None:
    check("confirmed_true -> 1", truth_binary("confirmed_true") == 1)
    check("likely_true -> 1", truth_binary("likely_true") == 1)
    check("unconfirmed -> 0", truth_binary("unconfirmed") == 0)
    check("confirmed_false -> 0", truth_binary("confirmed_false") == 0)
    check("None -> 0", truth_binary(None) == 0)


def test_metrics_empty() -> None:
    report = metrics([])
    check("empty -> resolved 0", report["resolved"] == 0)
    check("empty -> accuracy None", report["direction_accuracy"] is None)
    check("empty -> brier None", report["brier"] is None)
    check("empty -> calibration []", report["calibration"] == [])


def test_metrics_accuracy() -> None:
    rows = [event(), event(actual_direction="down"), event(actual_direction="flat")]
    report = metrics(rows)
    check("3 events, 1 hit", report["direction_hits"] == 1)
    check("accuracy 1/3", abs(report["direction_accuracy"] - 1 / 3) < 1e-9)


def test_metrics_brier() -> None:
    rows = [event(probability=1.0, actual_direction="up"), event(probability=0.0, actual_direction="down")]
    report = metrics(rows)
    check("perfect brier 0", abs(report["brier"] - 0.0) < 1e-9)
    rows2 = [event(probability=0.5, actual_direction="down"), event(probability=0.5, actual_direction="up")]
    check("coin-flip brier 0.25", abs(metrics(rows2)["brier"] - 0.25) < 1e-9)


def test_metrics_error() -> None:
    rows = [event(predicted_mean=1.0, actual_return=1.5), event(predicted_mean=2.0, actual_return=0.0)]
    report = metrics(rows)
    check("mae = (0.5 + 2.0)/2", abs(report["mean_abs_error_pct"] - 1.25) < 1e-9)
    check("signed bias = (0.5 - 2.0)/2", abs(report["signed_bias_pct"] - (-0.75)) < 1e-9)


def test_calibration_bins() -> None:
    rows = [
        event(probability=0.20, actual_direction="up"),   # bin 0-25: pred .2, hit
        event(probability=0.10, actual_direction="down"), # bin 0-25: pred .1, miss
        event(probability=0.90, actual_direction="up"),   # bin 75-100: hit
        event(probability=0.95, actual_direction="down"), # bin 75-100: miss
    ]
    bins = calibration(rows)
    by_bin = {b["bin"]: b for b in bins}
    check("two populated bins", len(bins) == 2)
    low = by_bin.get("0-25%")
    high = by_bin.get("75-100%")
    check("0-25% bin mean pred 0.15", low and abs(low["mean_predicted"] - 0.15) < 1e-9)
    check("0-25% bin actual 0.5", low and abs(low["actual_rate"] - 0.5) < 1e-9)
    check("0-25% not overconfident", low and low["overconfident"] is False)
    check("75-100% bin mean pred 0.925", high and abs(high["mean_predicted"] - 0.925) < 1e-9)
    check("75-100% overconfident flagged", high and high["overconfident"] is True)
    over = calibration(
        [event(probability=0.90, actual_direction="down") for _ in range(3)]
    )
    check("90% with 0% hits flagged overconfident", over and over[0]["overconfident"] is True)


def test_verification_report() -> None:
    rows = [
        event(status="confirmed_true", truth_outcome="true"),
        event(status="confirmed_false", truth_outcome="false"),
        event(status="unconfirmed", truth_outcome="true"),
        {"actual_direction": "up", "truth_outcome": None},
    ]
    report = verification_report(rows)
    check("3 truth rows, 2 agree", report["resolved_with_truth"] == 3
          and abs(report["verification_agreement"] - round(2 / 3, 3)) < 1e-9)
    check("empty -> None", verification_report([])["verification_agreement"] is None)


def test_drift_report() -> None:
    check("no stats", drift_report([])["scans"] == 0)
    stats = [
        {"items_stored": 10, "narratives": 2, "verdicts": '{"unconfirmed": 2}'},
        {"items_stored": 3, "narratives": 1, "verdicts": '{"confirmed_false": 1}'},
    ]
    report = drift_report(stats)
    check("scans counted", report["scans"] == 2)
    check("latest values used", report["latest_items_stored"] == 3 and report["latest_narratives"] == 1)


def test_storage_outcome_roundtrip() -> None:
    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "t.db")
            await storage.init()
            event_id = await storage.insert_impact_event(
                {
                    "asset": "BTC",
                    "category": "etf",
                    "horizon_hours": 24,
                    "first_seen": "2026-01-01T00:00:00",
                    "measured_return": 0.5,
                    "fomo_score": 50.0,
                    "epistemic_status": "unconfirmed",
                    "confidence": 0.4,
                    "coordination": 30.0,
                    "predicted_direction": "up",
                    "predicted_probability": 0.65,
                    "predicted_mean_pct": 1.2,
                }
            )
            unresolved = await storage.load_unresolved_impact_events()
            check("event inserted as unresolved", len(unresolved) == 1)
            row = unresolved[0]
            check("prediction snapshot stored",
                  row["predicted_direction"] == "up"
                  and abs(row["predicted_probability"] - 0.65) < 1e-9
                  and abs(row["predicted_mean_pct"] - 1.2) < 1e-9)
            await storage.resolve_impact_event(event_id, -0.8, "down")
            unresolved = await storage.load_unresolved_impact_events()
            check("resolved event leaves the open queue", unresolved == [])
            rows = await storage.load_impact_events()
            check("outcome persisted", rows[0]["actual_direction"] == "down"
                  and abs(rows[0]["actual_return"] - (-0.8)) < 1e-9
                  and rows[0]["resolved_at"] is not None)

    import asyncio
    asyncio.run(run())


def test_storage_scan_stats() -> None:
    async def run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "t.db")
            await storage.init()
            check("no stats initially", await storage.load_scan_stats() == [])
            await storage.insert_scan_stat(
                {"items_fetched": 5, "items_stored": 3, "items_dup": 2, "narratives": 1, "verdicts": '{"unconfirmed": 1}'}
            )
            await storage.insert_scan_stat(
                {"items_fetched": 7, "items_stored": 0, "items_dup": 7, "narratives": 1, "verdicts": '{"confirmed_false": 1}'}
            )
            stats = await storage.load_scan_stats()
            check("two scans stored oldest-first", len(stats) == 2 and stats[0]["items_stored"] == 3)
            check("verdicts json kept", stats[1]["verdicts"] == '{"confirmed_false": 1}')

    import asyncio
    asyncio.run(run())


def main() -> None:
    print("[A02] phase 5 tests — learning, calibration, backtest, drift")
    test_resolved_events_filter()
    test_truth_binary()
    test_metrics_empty()
    test_metrics_accuracy()
    test_metrics_brier()
    test_metrics_error()
    test_calibration_bins()
    test_verification_report()
    test_drift_report()
    test_storage_outcome_roundtrip()
    test_storage_scan_stats()
    print(f"\nRESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
