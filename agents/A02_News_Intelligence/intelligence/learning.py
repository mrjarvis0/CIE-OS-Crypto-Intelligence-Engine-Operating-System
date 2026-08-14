"""Phase 5: outcome learning, calibration and backtest.

Scores are computed from resolved impact events only. The agent never emits a
single binary verdict: direction carries probability, calibration tracks whether
those probabilities are honest over time.

A quick note on terms:
    truth_binary = 1 when epistemic status is confirmatory (confirmed_true /
    likely_true), 0 otherwise. Direction is 'up'/'down'/'flat' vs 'actual'.
"""

from __future__ import annotations

from typing import Any

TRUE_STATUSES = {"confirmed_true", "likely_true"}

_CALIBRATION_BINS: tuple[tuple[float, float], ...] = (
    (0.0, 0.25),
    (0.25, 0.5),
    (0.5, 0.75),
    (0.75, 1.0),
)


def _brier_multi(predicted_probability: float, actual_binary: int) -> float:
    """Multi-class Brier: p vs {1 - p} against the two outcomes."""
    return (predicted_probability - actual_binary) ** 2


def truth_binary(status: str | None) -> int:
    """Map an epistemic status to a resolved truth label (1 = true)."""
    return 1 if status in TRUE_STATUSES else 0


def resolved_events(events: list[dict]) -> list[dict]:
    """Keep only events with an actual outcome recorded."""
    return [
        e
        for e in events
        if e.get("actual_direction") is not None and e.get("predicted_direction")
    ]


def metrics(events: list[dict]) -> dict[str, Any]:
    """Accuracy, Brier and impact-error statistics over resolved events."""

    resolved = resolved_events(events)
    out: dict[str, Any] = {
        "resolved": len(resolved),
        "direction_hits": 0,
        "direction_accuracy": None,
        "brier": None,
        "mean_abs_error_pct": None,
        "signed_bias_pct": None,
        "calibration": calibration(events),
    }
    if not resolved:
        return out

    hits = 0
    errors: list[float] = []
    briers: list[float] = []
    for e in resolved:
        if e["predicted_direction"] == e["actual_direction"]:
            hits += 1
        if e.get("actual_return") is not None and e.get("predicted_mean_pct") is not None:
            errors.append(abs(e["actual_return"] - e["predicted_mean_pct"]))
        p = e.get("predicted_probability")
        if p is not None:
            briers.append(_brier_multi(p, 1 if e["actual_direction"] == e["predicted_direction"] else 0))

    out["direction_hits"] = hits
    out["direction_accuracy"] = hits / len(resolved)
    if briers:
        out["brier"] = sum(briers) / len(briers)
    if errors:
        out["mean_abs_error_pct"] = sum(errors) / len(errors)
        out["signed_bias_pct"] = sum(
            e["actual_return"] - e["predicted_mean_pct"]
            for e in resolved
            if e.get("actual_return") is not None and e.get("predicted_mean_pct") is not None
        ) / len(errors)
    return out


def calibration(events: list[dict]) -> list[dict]:
    """Per-bin honesty check: mean predicted probability vs actual hit rate."""

    resolved = resolved_events(events)
    bins: list[dict] = []
    for lo, hi in _CALIBRATION_BINS:
        rows = [
            e
            for e in resolved
            if e.get("predicted_probability") is not None and lo <= e["predicted_probability"] < hi
        ]
        if not rows:
            continue
        mean_pred = sum(e["predicted_probability"] for e in rows) / len(rows)
        actual_rate = sum(
            1 for e in rows if e["predicted_direction"] == e["actual_direction"]
        ) / len(rows)
        bins.append(
            {
                "bin": f"{int(lo * 100)}-{int(hi * 100)}%",
                "n": len(rows),
                "mean_predicted": round(mean_pred, 3),
                "actual_rate": round(actual_rate, 3),
                "delta": round(actual_rate - mean_pred, 3),
                "overconfident": (actual_rate - mean_pred) < -0.05,
            }
        )
    return bins


def verification_report(events: list[dict]) -> dict[str, Any]:
    """How often the verification layer's truth label matched the outcome."""

    rows = [
        e
        for e in events
        if e.get("truth_outcome") is not None
    ]
    agreed = sum(
        1
        for e in rows
        if (e["truth_outcome"] in {"true", "confirmed"} and truth_binary(e.get("epistemic_status")))
        or (e["truth_outcome"] in {"false", "denied"} and not truth_binary(e.get("epistemic_status")))
    )
    return {
        "resolved_with_truth": len(rows),
        "verification_agreement": round(agreed / len(rows), 3) if rows else None,
    }


def drift_report(stats: list[dict]) -> dict[str, Any]:
    """Trend of verdict distribution across scans (false-positive drift watch)."""

    if not stats:
        return {"scans": 0, "note": "no scan stats recorded yet"}
    latest = stats[-1]
    return {
        "scans": len(stats),
        "latest_items_stored": latest.get("items_stored", 0),
        "latest_narratives": latest.get("narratives", 0),
        "latest_verdicts": latest.get("verdicts", "{}"),
    }


__all__ = [
    "metrics",
    "calibration",
    "verification_report",
    "drift_report",
    "truth_binary",
    "resolved_events",
]
