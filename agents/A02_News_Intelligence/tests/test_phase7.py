"""
CIE-OS
A02 News Intelligence Agent

Phase 7 tests — Reddit connector, transformer fake detector, multi-asset correlation, retraining utils (offline).
Run directly:
    python agents/A02_News_Intelligence/tests/test_phase7.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agents.A02_News_Intelligence.core.phase7 import (
    TransformerFakeDetector,
    classify_fake_transformer,
    compute_cross_asset_correlation,
    predict_multi_asset,
)
from agents.A02_News_Intelligence.core.fetch import fetch_reddit_sync

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


def test_transformer_fake_detector_fallback() -> None:
    """Transformer detector falls back to rules when transformers not installed."""
    detector = TransformerFakeDetector("nonexistent-model")
    label, conf = detector.predict("This is a normal news article")
    check("fallback works", label in ("FAKE", "REAL") and 0 <= conf <= 1)

    # Fabrication marker
    label2, conf2 = detector.predict("This is satire from The Onion")
    check("fabrication detected by fallback", label2 == "FAKE")


def test_classify_fake_transformer() -> None:
    """Convenience function works."""
    label, conf = classify_fake_transformer("Normal article about market")
    check("convenience function works", label in ("FAKE", "REAL"))


def test_cross_asset_correlation() -> None:
    """Correlation computation with synthetic events."""
    events = [
        {"asset": "BTC", "first_seen": "2026-01-01T00:00:00", "measured_return": 1.0},
        {"asset": "ETH", "first_seen": "2026-01-01T01:00:00", "measured_return": 0.8},
        {"asset": "BTC", "first_seen": "2026-01-02T00:00:00", "measured_return": -0.5},
        {"asset": "ETH", "first_seen": "2026-01-02T01:00:00", "measured_return": -0.4},
        {"asset": "BTC", "first_seen": "2026-01-03T00:00:00", "measured_return": 2.0},
        {"asset": "ETH", "first_seen": "2026-01-03T01:00:00", "measured_return": 1.6},
        {"asset": "BTC", "first_seen": "2026-01-04T00:00:00", "measured_return": 0.3},
        {"asset": "ETH", "first_seen": "2026-01-04T01:00:00", "measured_return": 0.2},
        {"asset": "BTC", "first_seen": "2026-01-05T00:00:00", "measured_return": -1.0},
        {"asset": "ETH", "first_seen": "2026-01-05T01:00:00", "measured_return": -0.8},
    ]
    corr = compute_cross_asset_correlation(events, "BTC", "ETH")
    check("correlation computed", corr is not None and 0.8 < corr <= 1.0)

    # Anti-correlated
    events2 = [
        {"asset": "BTC", "first_seen": "2026-01-01T00:00:00", "measured_return": 1.0},
        {"asset": "SOL", "first_seen": "2026-01-01T01:00:00", "measured_return": -1.0},
        {"asset": "BTC", "first_seen": "2026-01-02T00:00:00", "measured_return": -0.5},
        {"asset": "SOL", "first_seen": "2026-01-02T01:00:00", "measured_return": 0.5},
        {"asset": "BTC", "first_seen": "2026-01-03T00:00:00", "measured_return": 2.0},
        {"asset": "SOL", "first_seen": "2026-01-03T01:00:00", "measured_return": -2.0},
        {"asset": "BTC", "first_seen": "2026-01-04T00:00:00", "measured_return": 0.3},
        {"asset": "SOL", "first_seen": "2026-01-04T01:00:00", "measured_return": -0.3},
        {"asset": "BTC", "first_seen": "2026-01-05T00:00:00", "measured_return": -1.0},
        {"asset": "SOL", "first_seen": "2026-01-05T01:00:00", "measured_return": 1.0},
    ]
    corr2 = compute_cross_asset_correlation(events2, "BTC", "SOL")
    check("negative correlation", corr2 is not None and corr2 < -0.8)

    # Insufficient data
    corr3 = compute_cross_asset_correlation([{"asset": "BTC", "first_seen": "2026-01-01T00:00:00", "measured_return": 1.0}], "BTC", "ETH")
    check("insufficient data -> None", corr3 is None)


def test_predict_multi_asset() -> None:
    """Multi-asset prediction propagation."""
    events = [
        {"asset": "BTC", "first_seen": "2026-01-01T00:00:00", "measured_return": 1.0},
        {"asset": "ETH", "first_seen": "2026-01-01T01:00:00", "measured_return": 0.8},
        {"asset": "BTC", "first_seen": "2026-01-02T00:00:00", "measured_return": -0.5},
        {"asset": "ETH", "first_seen": "2026-01-02T01:00:00", "measured_return": -0.4},
        {"asset": "BTC", "first_seen": "2026-01-03T00:00:00", "measured_return": 2.0},
        {"asset": "ETH", "first_seen": "2026-01-03T01:00:00", "measured_return": 1.6},
        {"asset": "BTC", "first_seen": "2026-01-04T00:00:00", "measured_return": 0.3},
        {"asset": "ETH", "first_seen": "2026-01-04T01:00:00", "measured_return": 0.2},
        {"asset": "BTC", "first_seen": "2026-01-05T00:00:00", "measured_return": -1.0},
        {"asset": "ETH", "first_seen": "2026-01-05T01:00:00", "measured_return": -0.8},
    ]
    primary = {"direction": "up", "probability": 0.7, "expected_mean_pct": 1.5}
    result = predict_multi_asset("BTC", primary, events, correlated_assets=["ETH"])
    check("ETH prediction generated", "ETH" in result)
    eth_pred = result["ETH"]
    check("direction propagated (positive corr)", eth_pred["direction"] == "up")
    check("probability scaled by corr", 0 < eth_pred["probability"] <= 0.7)
    check("expected return scaled", eth_pred["expected_return_pct"] > 0)


def test_reddit_sync_signature() -> None:
    """Reddit connector function exists and has correct signature."""
    import inspect
    sig = inspect.signature(fetch_reddit_sync)
    params = list(sig.parameters.keys())
    check("reddit fetch has client_id", "client_id" in params)
    check("reddit fetch has client_secret", "client_secret" in params)
    check("reddit fetch has subreddits", "subreddits" in params)


def main() -> None:
    print("[A02] phase 7 tests — Reddit, transformer, multi-asset, retraining")
    test_transformer_fake_detector_fallback()
    test_classify_fake_transformer()
    test_cross_asset_correlation()
    test_predict_multi_asset()
    test_reddit_sync_signature()
    print(f"\nRESULT: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()