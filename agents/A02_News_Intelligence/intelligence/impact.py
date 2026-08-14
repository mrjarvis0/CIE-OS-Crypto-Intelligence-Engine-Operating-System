"""
CIE-OS
A02 News Intelligence Agent

Module:
    intelligence.impact

Purpose:
    Event-study impact measurement (Phase 4+):
    - compute asset returns around a narrative's first_seen over
      1h / 6h / 24h horizons, plus volatility and volume surge
    - regime-aware volatility (GARCH-like)
    - options-implied volatility integration (stub)
    - jump detection and tail risk metrics
    - liquidity impact assessment

    Pure functions — candle series in, metrics out.
"""

from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.A02_News_Intelligence.core.models import NormalizedItem

from agents.A02_News_Intelligence.config.constants import DEFAULT_IMPACT_HORIZONS_HOURS

# ==============================================================================
# HELPERS
# ==============================================================================


def _price_at(candles: list[dict], moment: datetime) -> float | None:
    """Return the last close at or before `moment`."""

    target = moment.isoformat()
    best: float | None = None
    for candle in candles:
        if candle["open_time"] <= target:
            best = float(candle["close"])
        else:
            break
    return best


def price_before(candles: list[dict], moment: datetime, window_hours: int) -> float | None:
    """Close price `window_hours` before `moment` (baseline)."""

    return _price_at(candles, moment - timedelta(hours=window_hours))


def price_after(candles: list[dict], moment: datetime, window_hours: int) -> float | None:
    """Close price `window_hours` after `moment`."""

    return _price_at(candles, moment + timedelta(hours=window_hours))


def returns_at_horizons(candles: list[dict], t0: datetime) -> dict[int, float | None]:
    """Return percent returns at each horizon vs price just before t0."""

    base = _price_at(candles, t0)
    if not base:
        return {h: None for h in DEFAULT_IMPACT_HORIZONS_HOURS}
    results: dict[int, float | None] = {}
    for horizon in DEFAULT_IMPACT_HORIZONS_HOURS:
        after = price_after(candles, t0, horizon)
        results[horizon] = round(((after - base) / base) * 100, 3) if after else None
    return results


# ==============================================================================
# REGIME-AWARE VOLATILITY (GARCH-like)
# ==============================================================================


def _ewma_volatility(returns: list[float], lambda_: float = 0.94) -> float | None:
    """Exponentially weighted moving average volatility (RiskMetrics style).
    
    lambda_=0.94 is the standard RiskMetrics decay factor for daily data.
    For hourly data, use lambda_=0.97-0.99.
    """
    if len(returns) < 5:
        return None
    var = returns[0] ** 2
    for r in returns[1:]:
        var = lambda_ * var + (1 - lambda_) * (r ** 2)
    return math.sqrt(var) * 100  # as percentage


def _garch11_volatility(returns: list[float], 
                        omega: float = 0.000001, 
                        alpha: float = 0.1, 
                        beta: float = 0.85) -> float | None:
    """Simple GARCH(1,1) volatility estimation.
    
    sigma^2_t = omega + alpha * r^2_{t-1} + beta * sigma^2_{t-1}
    
    Parameters are typical for hourly crypto returns.
    """
    if len(returns) < 10:
        return None
    
    # Initialize with sample variance
    var = statistics.variance(returns) if len(returns) > 1 else returns[0] ** 2
    
    for r in returns[1:]:
        var = omega + alpha * (r ** 2) + beta * var
    
    return math.sqrt(var) * 100  # as percentage


def volatility_percent(candles: list[dict], window_hours: int = 24, method: str = "garch") -> float | None:
    """Volatility proxy with multiple methods.
    
    Methods:
    - "std": simple standard deviation of hourly returns
    - "ewma": exponentially weighted moving average (RiskMetrics)
    - "garch": GARCH(1,1) volatility (default, best for fat tails)
    """
    closes = [float(c["close"]) for c in candles[-window_hours:] if c["close"]]
    if len(closes) < 5:
        return None
    
    hourly = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    
    if method == "std":
        mean = sum(hourly) / len(hourly)
        variance = sum((r - mean) ** 2 for r in hourly) / len(hourly)
        return round(math.sqrt(variance) * 100, 3)
    elif method == "ewma":
        return round(_ewma_volatility(hourly, lambda_=0.97) or 0, 3)
    elif method == "garch":
        return round(_garch11_volatility(hourly) or 0, 3)
    else:
        return round(statistics.stdev(hourly) * 100, 3) if len(hourly) > 1 else None


def realized_volatility(candles: list[dict], window_hours: int = 24) -> float | None:
    """Realized volatility (sum of squared returns) over window."""
    closes = [float(c["close"]) for c in candles[-window_hours:] if c["close"]]
    if len(closes) < 2:
        return None
    hourly = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    rv = sum(r ** 2 for r in hourly)
    return round(math.sqrt(rv) * 100 * math.sqrt(24), 3)  # daily-ized


def jump_test(candles: list[dict], threshold_sigma: float = 3.0) -> dict:
    """Detect price jumps using Lee-Mykland test (simplified).
    
    Returns dict with jump_count, jump_times, jump_sizes.
    """
    closes = [float(c["close"]) for c in candles if c["close"]]
    if len(closes) < 20:
        return {"jump_count": 0, "jumps": []}
    
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    mean_r = sum(returns) / len(returns)
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / len(returns))
    
    # Handle zero variance (steady trend) - use minimum threshold
    # Also check if returns are a steady trend (all same sign, low variance)
    min_threshold = 0.005  # 0.5% minimum to avoid flagging steady trends
    threshold = max(threshold_sigma * std_r, min_threshold)
    
    # Additional check: if returns are all same direction and low variance, don't flag as jumps
    all_same_sign = all(r * mean_r > 0 for r in returns) if mean_r != 0 else False
    low_variance = std_r < 0.002  # 0.2% std
    
    jumps = []
    
    for i, r in enumerate(returns):
        if abs(r - mean_r) > threshold:
            # Don't flag steady trends as jumps
            if all_same_sign and low_variance:
                continue
            jumps.append({
                "index": i,
                "return_pct": round(r * 100, 3),
                "sigma_multiple": round(abs(r - mean_r) / std_r, 1),
            })
    
    return {
        "jump_count": len(jumps),
        "jumps": jumps,
        "threshold_sigma": threshold_sigma,
    }


# ==============================================================================
# VOLUME & LIQUIDITY
# ==============================================================================


def volume_surge(candles: list[dict], t0: datetime, window_hours: int = 6) -> float | None:
    """Ratio of average hourly volume after t0 vs before t0 (1.0 = flat)."""

    before = [float(c["volume"]) for c in candles if c["open_time"] <= t0.isoformat()][-window_hours:]
    after = [float(c["volume"]) for c in candles if c["open_time"] > t0.isoformat()][:window_hours]
    if not before or not after or sum(before) == 0:
        return None
    return round((sum(after) / len(after)) / (sum(before) / len(before)), 3)


def volume_weighted_volatility(candles: list[dict], window_hours: int = 24) -> float | None:
    """Volume-weighted volatility (proxy for liquidity-adjusted risk)."""
    recent = candles[-window_hours:]
    if len(recent) < 5:
        return None
    
    vol_sum = 0.0
    vol_weight_sum = 0.0
    for c in recent:
        vol = float(c["volume"])
        if vol > 0:
            # Simple return
            idx = candles.index(c)
            if idx > 0:
                prev_close = float(candles[idx - 1]["close"])
                ret = (float(c["close"]) - prev_close) / prev_close
                vol_sum += vol * (ret ** 2)
                vol_weight_sum += vol
    
    if vol_weight_sum == 0:
        return None
    return round(math.sqrt(vol_sum / vol_weight_sum) * 100, 3)


def amihud_illiquidity(candles: list[dict], window_hours: int = 24) -> float | None:
    """Amihud illiquidity ratio: average |return| / volume.
    
    Higher = less liquid.
    """
    recent = candles[-window_hours:]
    if len(recent) < 5:
        return None
    
    ratios = []
    for i in range(1, len(recent)):
        vol = float(recent[i]["volume"])
        if vol > 0:
            ret = abs((float(recent[i]["close"]) - float(recent[i-1]["close"])) / float(recent[i-1]["close"]))
            ratios.append(ret / vol)
    
    if not ratios:
        return None
    return round(sum(ratios) / len(ratios), 6)


# ==============================================================================
# OPTIONS IMPLIED VOLATILITY (stub for future integration)
# ==============================================================================


class OptionsDataProvider:
    """Stub for options data provider (Deribit, Binance Options, etc.)."""
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self.enabled = api_key is not None
    
    def get_implied_volatility(self, symbol: str, expiry_days: int = 7) -> float | None:
        """Get ATM implied volatility for symbol.
        
        Returns annualized IV as decimal (e.g., 0.8 for 80%).
        """
        if not self.enabled:
            return None
        # TODO: Implement actual options chain fetching
        # - Deribit: /get_instruments + /get_order_book for ATM option
        # - Binance Options: /eapi/v1/mark
        # - Parse ATM IV from options chain
        return None
    
    def get_iv_term_structure(self, symbol: str) -> dict[int, float] | None:
        """Get IV term structure (days to expiry -> IV)."""
        if not self.enabled:
            return None
        return None
    
    def get_skew(self, symbol: str, expiry_days: int = 7) -> float | None:
        """Get 25-delta risk reversal (put IV - call IV)."""
        if not self.enabled:
            return None
        return None


def get_options_provider() -> OptionsDataProvider:
    """Get options data provider instance."""
    from agents.A02_News_Intelligence.config.settings import get_settings
    settings = get_settings()
    # Check for options API keys in settings
    api_key = getattr(settings.market, "options_api_key", None)
    return OptionsDataProvider(api_key)


# ==============================================================================
# SEVERITY & TAIL RISK
# ==============================================================================


def severity_label(return_pct: float | None, volatility: float | None) -> str:
    """Mild / moderate / severe based on move vs volatility."""

    if return_pct is None:
        return "unknown"
    scale = abs(return_pct) / (volatility * 3 if volatility else 1.0)
    if scale >= 2.0:
        return "severe"
    if scale >= 0.8:
        return "moderate"
    return "mild"


def tail_risk_metrics(candles: list[dict], window_hours: int = 24) -> dict:
    """Tail risk metrics: VaR, CVaR, max drawdown."""
    closes = [float(c["close"]) for c in candles[-window_hours:] if c["close"]]
    if len(closes) < 10:
        return {"var_95": None, "cvar_95": None, "max_drawdown_pct": None}
    
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    sorted_rets = sorted(returns)
    n = len(sorted_rets)
    
    # VaR 95%
    var_idx = max(0, int(0.05 * n) - 1)
    var_95 = sorted_rets[var_idx] * 100 if var_idx < n else None
    
    # CVaR 95% (expected shortfall)
    cvar_idx = max(0, int(0.05 * n))
    cvar_95 = sum(sorted_rets[:cvar_idx]) / cvar_idx * 100 if cvar_idx > 0 else None
    
    # Max drawdown
    peak = closes[0]
    max_dd = 0.0
    for price in closes:
        if price > peak:
            peak = price
        dd = (peak - price) / peak
        if dd > max_dd:
            max_dd = dd
    
    return {
        "var_95_pct": round(var_95, 3) if var_95 else None,
        "cvar_95_pct": round(cvar_95, 3) if cvar_95 else None,
        "max_drawdown_pct": round(max_dd * 100, 3),
    }


# ==============================================================================
# FULL MEASURED IMPACT
# ==============================================================================


def compute_measured_impact(
    candles: list[dict], 
    t0: datetime,
    volatility_method: str = "garch",
) -> dict:
    """Full measured-impact bundle for one asset at t0."""

    t0 = t0.replace(tzinfo=UTC) if t0.tzinfo is None else t0
    returns = returns_at_horizons(candles, t0)
    volatility = volatility_percent(candles, method=volatility_method)
    surge = volume_surge(candles, t0)
    primary_horizon = max((h for h, r in returns.items() if r is not None), default=None)
    primary_return = returns.get(primary_horizon) if primary_horizon else None
    
    # Enhanced metrics
    rv = realized_volatility(candles)
    jumps = jump_test(candles)
    vwv = volume_weighted_volatility(candles)
    illiq = amihud_illiquidity(candles)
    tail = tail_risk_metrics(candles)
    
    # Options IV (if available)
    options_provider = get_options_provider()
    iv = None
    if options_provider.enabled:
        symbol = candles[0]["symbol"] if candles else None
        if symbol:
            iv = options_provider.get_implied_volatility(symbol)
    
    return {
        "returns": returns,
        "primary_return_pct": primary_return,
        "volatility_pct": volatility,
        "realized_vol_pct": rv,
        "volume_surge": surge,
        "severity": severity_label(primary_return, volatility),
        # Enhanced
        "jump_count": jumps["jump_count"],
        "jumps": jumps["jumps"],
        "volume_weighted_vol_pct": vwv,
        "amihud_illiquidity": illiq,
        "var_95_pct": tail["var_95_pct"],
        "cvar_95_pct": tail["cvar_95_pct"],
        "max_drawdown_pct": tail["max_drawdown_pct"],
        "implied_vol": iv,
    }


__all__ = [
    "price_before",
    "price_after",
    "returns_at_horizons",
    "volatility_percent",
    "realized_volatility",
    "jump_test",
    "volume_surge",
    "volume_weighted_volatility",
    "amihud_illiquidity",
    "get_options_provider",
    "OptionsDataProvider",
    "severity_label",
    "tail_risk_metrics",
    "compute_measured_impact",
]