"""
CIE-OS
A02 News Intelligence Agent

Module:
    intelligence.predict

Purpose:
    Market impact prediction (Phase 4+, enhanced).

    Combines:
        - measured impact (price move since first_seen)
        - historical analog (similar past events)
        - narrative intelligence (verification, FOMO, coordination)
        - regime-aware volatility & tail risk
        - options-implied signals (stub)

    Output: probability + range + confidence — never certainty.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .history import classify_category, expected_impact, find_similar_events
from .impact import (
    compute_measured_impact,
    severity_label,
    tail_risk_metrics,
    jump_test,
    realized_volatility,
)
from .verification import verify_narrative


class AssetPrediction(BaseModel):
    """Prediction for one asset affected by a narrative."""

    asset: str
    category: str = "general"
    direction: str = "unknown"
    probability: float = 0.0
    expected_low_pct: float | None = None
    expected_high_pct: float | None = None
    expected_mean_pct: float | None = None
    volatility_pct: float | None = None
    realized_vol_pct: float | None = None
    volume_surge: float | None = None
    severity: str = "unknown"
    measured_returns_pct: dict[int, float | None] = Field(default_factory=dict)
    historical_similarity: float = 0.0
    historical_events_used: int = 0
    main_risk: str = "no historical analog"
    # Enhanced fields
    jump_count: int = 0
    jumps: list[dict] = Field(default_factory=list)
    var_95_pct: float | None = None
    cvar_95_pct: float | None = None
    max_drawdown_pct: float | None = None
    implied_vol: float | None = None
    regime: str = "normal"  # normal, high_vol, crisis, recovery
    risk_factors: list[str] = Field(default_factory=list)


def _direction_of(mean: float | None, probability: float) -> str:
    if mean is None:
        return "unknown"
    if abs(mean) < 0.1:
        return "flat"
    return "up" if mean > 0 else "down"


def _detect_regime(volatility_pct: float | None, jump_count: int, 
                   tail_metrics: dict) -> str:
    """Detect market regime from volatility and tail metrics."""
    if volatility_pct is None:
        return "normal"
    
    vol = volatility_pct
    if vol > 5.0:  # >5% hourly vol = crisis
        return "crisis"
    elif vol > 2.0:  # >2% hourly vol = high volatility
        return "high_vol"
    elif volatility_pct is not None and vol < 0.5:
        return "low_vol"
    return "normal"


def _assess_risk_factors(
    narrative,
    measured: dict,
    analog: dict | None,
    tail: dict,
    jumps: dict,
) -> list[str]:
    """Identify key risk factors for the prediction."""
    risks = []
    
    # Narrative risks
    if narrative.epistemic_status in ("confirmed_false", "likely_false", "fabricated"):
        risks.append("narrative likely false — impact may reverse")
    elif narrative.epistemic_status == "disputed":
        risks.append("conflicting sources — high uncertainty")
    elif narrative.epistemic_status == "unconfirmed":
        risks.append("unverified claim — treat with caution")
    
    # Market risks
    if measured:
        if measured.get("jump_count", 0) > 2:
            risks.append("multiple price jumps detected — unstable")
        if measured.get("var_95_pct") and measured["var_95_pct"] < -3:
            risks.append("high tail risk (VaR95 < -3%)")
    
    if tail.get("max_drawdown_pct", 0) > 10:
        risks.append(f"recent max drawdown {tail['max_drawdown_pct']:.1f}%")
    
    if jumps.get("jump_count", 0) > 0:
        risks.append(f"{jumps['jump_count']} price jump(s) in recent history")
    
    # Historical risks
    if not analog:
        risks.append("no historical analog — pure speculation")
    elif analog.get("used", 0) < 3:
        risks.append("historical sample is small")
    elif analog.get("similarity", 0) < 0.5:
        risks.append("low historical similarity — analog quality poor")
    
    # Verification risks
    if narrative.confidence < 0.4:
        risks.append("low verification confidence")
    
    # Coordination risk
    if narrative.coordination_score > 60:
        risks.append("coordinated amplification detected — manipulation risk")
    
    return risks if risks else ["standard market risk"]


def predict_asset(
    asset: str,
    narrative,
    candles: list[dict] | None = None,
    history_events: list[dict] | None = None,
) -> AssetPrediction:
    """Build a prediction for one asset from narrative + candles + history."""

    from .history import classify_category, expected_impact, find_similar_events
    from .impact import (
        compute_measured_impact,
        severity_label,
        tail_risk_metrics,
        jump_test,
        realized_volatility,
    )

    category = classify_category(narrative.claim_text)
    measured = compute_measured_impact(candles, narrative.first_seen) if candles else None

    similar = (
        find_similar_events(history_events, category, narrative.fomo_score, asset)
        if history_events
        else []
    )
    analog = expected_impact(similar, asset)

# Enhanced metrics
    tail = tail_risk_metrics(candles) if candles else {}
    jumps = jump_test(candles) if candles else {"jump_count": 0, "jumps": []}
    rv = realized_volatility(candles) if candles else None

    # Primary expectation: measured first, historical analog second
    measured_mean = measured["primary_return_pct"] if measured else None
    mean = measured_mean if measured_mean is not None else (analog["mean"] if analog else None)
    low = analog["low"] if analog else None
    high = analog["high"] if analog else None
    if measured_mean is not None:
        # measured move is fact; the analog range narrows/expands around it
        if analog:
            low = round(measured_mean - (analog["high"] - analog["low"]) / 2, 3)
            high = round(measured_mean + (analog["high"] - analog["low"]) / 2, 3)

    # Probability: verification confidence weighted with analog confidence
    prob = max(0.05, min(0.95, narrative.confidence * 0.6 + (analog["confidence"] if analog else 0.0) * 0.4))

    # Detect regime
    vol = measured.get("volatility_pct") if measured else None
    regime = _detect_regime(vol, jumps.get("jump_count", 0), {}) if measured else "normal"

    # Risk factors
    risk_factors = _assess_risk_factors(narrative, measured or {}, analog, tail, jumps)

    # Main risk (most important)
    main_risk = risk_factors[0] if risk_factors else "standard market risk"

    return AssetPrediction(
        asset=asset,
        category=category,
        direction=_direction_of(mean, prob),
        probability=round(prob, 2),
        expected_low_pct=low,
        expected_high_pct=high,
        expected_mean_pct=mean,
        volatility_pct=measured.get("volatility_pct") if measured else None,
        realized_vol_pct=rv,
        volume_surge=measured.get("volume_surge") if measured else None,
        severity=measured.get("severity", "unknown") if measured else "unknown",
        measured_returns_pct=measured.get("returns", {}) if measured else {},
        historical_similarity=analog["similarity"] if analog else 0.0,
        historical_events_used=analog["used"] if analog else 0,
        main_risk=main_risk,
        # Enhanced fields
        jump_count=measured.get("jump_count", 0) if measured else 0,
        jumps=measured.get("jumps", []) if measured else [],
        var_95_pct=measured.get("var_95_pct") if measured else None,
        cvar_95_pct=measured.get("cvar_95_pct") if measured else None,
        max_drawdown_pct=measured.get("max_drawdown_pct") if measured else None,
        implied_vol=measured.get("implied_vol") if measured else None,
        regime=regime,
        risk_factors=risk_factors,
    )


__all__ = ["AssetPrediction", "predict_asset"]