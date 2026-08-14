"""
CIE-OS
A02 News Intelligence Agent

Module:
    intelligence.history

Purpose:
    Historical correlation engine (Phase 4+6):
    - classify a claim into an impact category (rules + ML)
    - find similar past impact events
    - produce expected impact range + confidence from the analog set

    Philosophy: predictions are probability + range + confidence,
    never certainty.
"""

from __future__ import annotations

import re

try:
    from agents.A02_News_Intelligence.models.ml_models import classify_category_ml
    ML_AVAILABLE = True
except Exception:
    ML_AVAILABLE = False

# ==============================================================================
# CATEGORIES (extended in Phase 6)
# ==============================================================================

_CATEGORY_RULES: tuple[tuple[str, re.Pattern], ...] = (
    # Phase 6 specific categories first — must come before broader categories
    ("etf", re.compile(r"\b(etf|exchange[- ]traded fund)\b", re.I)),
    ("hack", re.compile(r"\b(hack|hacked|exploit|exploited|drain|stolen|breach|vulnerability|stole)\b", re.I)),
    ("delisting", re.compile(r"\b(delist|delisting|removal|remove.*list|suspended|suspension)\b", re.I)),
    ("fraud", re.compile(r"\b(fraud|scam|ponzi|pump and dump|manipulation|insider trading|misrepresent)\b", re.I)),
    ("product_launch", re.compile(r"\b(launch|mainnet|release|v\d+\.\d+|upgrade|fork|hard fork|soft fork|testnet)\b", re.I)),
    ("executive_change", re.compile(r"\b(ceo|cfo|cto|president|chairman|founder|executive|director) (?:steps? down|resigns?|appointed|hired|leaves?|departs?)\b", re.I)),
    ("merger_acquisition", re.compile(r"\b(merger|acquisition|acquires|buyout|takeover|merges with|purchased by)\b", re.I)),
    ("guidance_change", re.compile(r"\b(guidance|outlook|forecast|projection) (?:raised|lowered|increased|decreased|revised|updated)\b", re.I)),
    ("dividend", re.compile(r"\b(dividend|distribution|payout|yield) (?:increased|raised|declared|announced|cut|suspended)\b", re.I)),
    ("stock_split", re.compile(r"\b(stock split|reverse split|split ratio)\b", re.I)),
    ("bankruptcy", re.compile(r"\b(bankruptcy|chapter 11|chapter 7|insolvent|liquidation|receivership)\b", re.I)),
    ("clinical_trial", re.compile(r"\b(clinical trial|phase [123]|fda approval|drug approval|trial results)\b", re.I)),
    ("patent", re.compile(r"\b(patent|patented|patent granted|intellectual property|ip filing)\b", re.I)),
    ("contract_win", re.compile(r"\b(contract awarded|government contract|enterprise deal|major deal|partnership agreement)\b", re.I)),
    ("investigation", re.compile(r"\b(investigation|probe|inquiry|investigated|subpoena|doj|sec investigation)\b", re.I)),
    ("sanctions", re.compile(r"\b(sanctions|sanctioned|ofac|sdn list|treasury sanctions|embargo)\b", re.I)),
    # Broader categories after specifics
    ("earnings", re.compile(r"\b(earnings|revenue|q[1-4] (?:results|report)|profit)\b", re.I)),
    ("partnership", re.compile(r"\b(partnership|partners with|invests in)\b", re.I)),
    ("macro", re.compile(r"\b(inflation|interest rate|fed|federal reserve|gdp|unemployment|tariff|rates? (?:hike|cut)|recession)\b", re.I)),
    ("regulatory", re.compile(r"\b(sec|fcc|regulator|regulation|ban|banned|lawsuit|indictment|charge|sued|unregistered|class action)\b", re.I)),
)


def classify_category(claim_text: str, use_ml: bool = True) -> str:
    """Map a claim to its impact category ('general' when unmatched).

    Tries ML first (if available and use_ml=True), falls back to rules.
    """

    if use_ml and ML_AVAILABLE:
        try:
            ml_result = classify_category_ml(claim_text)
            if ml_result != "general":
                return ml_result
        except Exception:
            pass
    # Rule fallback
    for category, pattern in _CATEGORY_RULES:
        if pattern.search(claim_text):
            return category
    return "general"


# ==============================================================================
# SIMILARITY
# ==============================================================================


def fomo_bucket(fomo: float) -> int:
    """Bucket FOMO 0-100 into 0-4 buckets for similarity matching."""

    return min(4, int(fomo) // 20)


def event_score(event: dict, category: str, fomo: float, entity_type: str | None) -> float:
    """Similarity of a stored event to the current narrative (0..1)."""

    score = 0.0
    if event.get("category") == category:
        score += 0.5
    elif category == "general":
        score += 0.2
    bucket_gap = abs(fomo_bucket(event.get("fomo_score") or 0) - fomo_bucket(fomo))
    score += max(0.0, 0.3 - 0.1 * bucket_gap)
    if event.get("epistemic_status") in ("confirmed_true", "likely_true"):
        score += 0.1
    if event.get("asset") == entity_type:
        score += 0.1
    return round(min(1.0, score), 3)


def find_similar_events(events: list[dict], category: str, fomo: float, entity_type: str | None = None, k: int = 3) -> list[tuple[dict, float]]:
    """Top-k most similar past events with their similarity scores."""

    scored = [(event, event_score(event, category, fomo, entity_type)) for event in events]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [(event, score) for event, score in scored[:k] if score > 0.05]


def expected_impact(similar: list[tuple[dict, float]], entity_type: str | None = None) -> dict | None:
    """Weighted expected impact from similar events.

    Returns {mean, low, high, confidence, similarity, used} or None
    when there is nothing usable.
    """

    usable = [(event, score) for event, score in similar if event.get("measured_return") is not None]
    if not usable:
        return None

    total_weight = sum(score for _, score in usable)
    mean = sum(event["measured_return"] * score for event, score in usable) / total_weight
    values = [event["measured_return"] for event, _ in usable]
    spread = max(values) - min(values)
    confidence = round(0.4 + 0.15 * (len(usable) / 3.0) + 0.1 * (sum(s for _, s in usable) / len(usable)), 2)
    confidence = min(0.85, confidence)
    return {
        "mean": round(mean, 3),
        "low": round(mean - spread / 2, 3),
        "high": round(mean + spread / 2, 3),
        "confidence": confidence,
        "similarity": round(total_weight / max(1.0, sum(s for _, s in similar)), 3) if similar else 0.0,
        "used": len(usable),
    }


__all__ = [
    "classify_category",
    "fomo_bucket",
    "event_score",
    "find_similar_events",
    "expected_impact",
]
