"""
CIE-OS A02
Phase 7: Reddit connector, transformer fake detector, multi-asset correlation, retraining utils.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agents.A02_News_Intelligence.core.models import RawItem
from agents.A02_News_Intelligence.core.normalize import parse_timestamp

if TYPE_CHECKING:
    from agents.A02_News_Intelligence.config.settings import Settings

_USER_AGENT = "Mozilla/5.0 (CIE-OS A02 News Intelligence Agent)"


def http_get_sync(url: str, headers: dict[str, str] | None = None, timeout: float = 30.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_reddit_sync(
    client_id: str,
    client_secret: str,
    user_agent: str,
    subreddits: list[str],
    limit: int,
    timeout: float,
) -> list[RawItem]:
    """Blocking Reddit API fetch (public read-only, no OAuth needed for listing)."""
    items: list[RawItem] = []
    for sub in subreddits:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit={min(limit, 100)}"
        headers = {"User-Agent": user_agent}
        try:
            payload = json.loads(http_get_sync(url, headers=headers, timeout=timeout))
        except Exception:
            continue
        for post in payload.get("data", {}).get("children", []):
            data = post.get("data", {})
            title = data.get("title") or ""
            if not title:
                continue
            content = data.get("selftext") or ""
            url_post = data.get("url")
            permalink = f"https://reddit.com{data.get('permalink', '')}"
            author = data.get("author")
            created = data.get("created_utc")
            published = datetime.fromtimestamp(created, UTC) if created else datetime.now(UTC)
            items.append(
                RawItem(
                    source="reddit",
                    source_key=f"reddit:{data.get('id')}",
                    url=permalink,
                    title=title,
                    content=content,
                    author=author,
                    published_at=published,
                    raw_json={"score": data.get("score", 0), "num_comments": data.get("num_comments", 0)},
                )
            )
    return items


# ==============================================================================
# PHASE 7: TRANSFORMER-BASED FAKE DETECTOR (lightweight framework)
# ==============================================================================

class TransformerFakeDetector:
    """
    Lightweight transformer-based fake news detector.
    
    Uses a distilled BERT-like model. In production, load a fine-tuned
    FinFakeBERT or similar. Here we provide the inference framework
    with a rule-based fallback for zero-dependency operation.
    """

    def __init__(self, model_name: str = "distilbert-base-uncased-finetuned-fake-news") -> None:
        self.model_name = model_name
        self._pipe = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            from transformers import pipeline
            self._pipe = pipeline("text-classification", model=self.model_name, truncation=True, max_length=512)
        except Exception:
            self._pipe = None

    def predict(self, text: str) -> tuple[str, float]:
        """
        Returns (label, confidence).
        Label: 'FAKE' or 'REAL' (for compatibility), but we map to our epistemic statuses.
        """
        if self._pipe is None:
            # Rule fallback: use verification rules
            from agents.A02_News_Intelligence.intelligence.verification import _FABRICATION_MARKERS
            if _FABRICATION_MARKERS.search(text):
                return ("FAKE", 0.8)
            return ("REAL", 0.5)
        try:
            result = self._pipe(text[:512])[0]
            label = result["label"].upper()
            score = float(result["score"])
            # Map common HF labels
            if label in ("LABEL_1", "FAKE", "FALSE", "FAKE_NEWS"):
                return ("FAKE", score)
            if label in ("LABEL_0", "REAL", "TRUE", "REAL_NEWS"):
                return ("REAL", score)
            return (label, score)
        except Exception:
            return ("REAL", 0.5)

    def predict_proba(self, text: str) -> dict[str, float]:
        if self._pipe is None:
            return {"FAKE": 0.3, "REAL": 0.7}
        try:
            results = self._pipe(text[:512], return_all_scores=True)[0]
            return {r["label"].upper(): float(r["score"]) for r in results}
        except Exception:
            return {"FAKE": 0.3, "REAL": 0.7}


# Singleton
_detector: TransformerFakeDetector | None = None


def get_fake_detector(model_name: str | None = None) -> TransformerFakeDetector:
    global _detector
    if _detector is None:
        _detector = TransformerFakeDetector(model_name or "distilbert-base-uncased-finetuned-fake-news")
    return _detector


def classify_fake_transformer(text: str, model_name: str | None = None) -> tuple[str, float]:
    """Convenience function for transformer fake detection."""
    return get_fake_detector(model_name).predict(text)


# ==============================================================================
# PHASE 7: MULTI-ASSET IMPACT CORRELATION
# ==============================================================================

def compute_cross_asset_correlation(
    events: list[dict],
    asset_a: str,
    asset_b: str,
    window_hours: int = 24,
) -> float | None:
    """
    Compute Pearson correlation of measured returns between two assets
    across shared historical impact events.
    
    Returns correlation coefficient [-1, 1] or None if insufficient data.
    """

    # Group events by asset
    events_a = [e for e in events if e.get("asset") == asset_a and e.get("first_seen") and e.get("measured_return") is not None]
    events_b = [e for e in events if e.get("asset") == asset_b and e.get("first_seen") and e.get("measured_return") is not None]

    if len(events_a) < 5 or len(events_b) < 5:
        return None

    # Parse timestamps
    for e in events_a:
        try:
            e["_dt"] = datetime.fromisoformat(e["first_seen"].replace("Z", "+00:00"))
        except Exception:
            e["_dt"] = None
    for e in events_b:
        try:
            e["_dt"] = datetime.fromisoformat(e["first_seen"].replace("Z", "+00:00"))
        except Exception:
            e["_dt"] = None

    events_a = [e for e in events_a if e["_dt"]]
    events_b = [e for e in events_b if e["_dt"]]

    returns_a = []
    returns_b = []
    for e_a in events_a:
        # Find closest event_b within window
        best_e_b = None
        best_diff = float("inf")
        for e_b in events_b:
            diff = abs((e_a["_dt"] - e_b["_dt"]).total_seconds())
            if diff < window_hours * 3600 and diff < best_diff:
                best_diff = diff
                best_e_b = e_b
        if best_e_b:
            returns_a.append(e_a["measured_return"])
            returns_b.append(best_e_b["measured_return"])

    if len(returns_a) < 5:
        return None

    # Pearson correlation - pure Python fallback if numpy not available
    try:
        import numpy as np
        return float(np.corrcoef(returns_a, returns_b)[0, 1])
    except Exception:
        n = len(returns_a)
        mean_a = sum(returns_a) / n
        mean_b = sum(returns_b) / n
        num = sum((a - mean_a) * (b - mean_b) for a, b in zip(returns_a, returns_b))
        den_a = sum((a - mean_a) ** 2 for a in returns_a) ** 0.5
        den_b = sum((b - mean_b) ** 2 for b in returns_b) ** 0.5
        if den_a == 0 or den_b == 0:
            return 0.0
        return num / (den_a * den_b)


def predict_multi_asset(
    primary_asset: str,
    primary_prediction: dict,
    events: list[dict],
    correlated_assets: list[str] | None = None,
    min_corr: float = 0.5,
) -> dict[str, dict]:
    """
    Given a primary asset prediction, propagate to correlated assets.
    
    Returns dict of {asset: {direction, probability, expected_return, confidence}}.
    """
    assets_to_check = correlated_assets or []
    if correlated_assets is None:
        # Auto-discover from history
        for asset in set(e.get("asset") for e in events):
            if asset != primary_asset:
                corr = compute_cross_asset_correlation(events, primary_asset, asset)
                if corr is not None and abs(corr) >= min_corr:
                    assets_to_check.append((asset, corr))

    out = {}
    for item in assets_to_check:
        if isinstance(item, tuple):
            asset, corr = item
        else:
            asset = item
            corr = compute_cross_asset_correlation(events, primary_asset, asset)
            if corr is None or abs(corr) < min_corr:
                continue

        # Propagate: direction same if positive corr, opposite if negative
        primary_dir = primary_prediction.get("direction", "flat")
        primary_prob = primary_prediction.get("probability", 0.5)
        primary_mean = primary_prediction.get("expected_mean_pct", 0.0)

        if corr > 0:
            direction = primary_dir
        else:
            direction = "down" if primary_dir == "up" else "up" if primary_dir == "down" else "flat"

        # Scale probability by correlation strength
        prob = primary_prob * abs(corr)
        expected = primary_mean * corr

        out[asset] = {
            "direction": direction,
            "probability": round(prob, 3),
            "expected_return_pct": round(expected, 4),
            "correlation": round(corr, 3),
            "confidence": "low" if abs(corr) < 0.7 else "medium",
        }
    return out


# ==============================================================================
# PHASE 7: ML RETRAINING UTILITIES
# ==============================================================================

def export_training_data(
    storage,
    output_path: str,
    min_confidence: float = 0.8,
) -> int:
    """
    Export resolved impact events as labeled training data for category/stance/verification models.
    
    Returns number of samples exported.
    """
    import asyncio

    async def run():
        events = await storage.load_impact_events()
        resolved = [e for e in events if e.get("actual_direction") is not None]
        samples = []
        for e in resolved:
            # Load narrative for claim text
            narrative_id = e.get("narrative_id")
            if not narrative_id:
                continue
            narratives = await storage.load_active_narratives("1970-01-01T00:00:00")
            narrative = next((n for n in narratives if n.get("id") == narrative_id), None)
            if not narrative:
                continue
            claim = narrative.get("claim_text", "")
            status = narrative.get("epistemic_status", "unconfirmed")
            if status in ("confirmed_true", "likely_true", "confirmed_false", "likely_false", "fabricated"):
                samples.append({
                    "text": claim,
                    "category": e.get("category", "general"),
                    "verification": status,
                    "direction": e.get("actual_direction", "flat"),
                    "confidence": e.get("confidence", 0.5),
                })
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(samples, f, ensure_ascii=False, indent=2)
        return len(samples)

    return asyncio.run(run())


def retrain_ml_models(
    training_path: str,
    model_dir: str = "agents/A02_News_Intelligence/models",
) -> dict[str, bool]:
    """
    Retrain all ML models from exported training data.
    
    Returns dict of {model_name: success}.
    """
    try:
        import pandas as pd
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        import pickle
        from pathlib import Path
    except Exception as exc:
        return {"error": f"sklearn/pandas not available: {exc}"}

    with open(training_path, encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)
    if df.empty:
        return {"error": "no training samples"}

    results = {}
    model_dir = Path(model_dir)
    model_dir.mkdir(exist_ok=True)

    # Category model
    if "category" in df.columns and df["category"].nunique() > 1:
        pipe_cat = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=5000)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
        ])
        pipe_cat.fit(df["text"], df["category"])
        with open(model_dir / "category_model.pkl", "wb") as f:
            pickle.dump(pipe_cat, f)
        results["category"] = True
    else:
        results["category"] = False

    # Verification model
    if "verification" in df.columns and df["verification"].nunique() > 1:
        pipe_ver = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=5000)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
        ])
        pipe_ver.fit(df["text"], df["verification"])
        with open(model_dir / "verification_model.pkl", "wb") as f:
            pickle.dump(pipe_ver, f)
        results["verification"] = True
    else:
        results["verification"] = False

    # Direction model (for impact)
    if "direction" in df.columns and df["direction"].nunique() > 1:
        pipe_dir = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=5000)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
        ])
        pipe_dir.fit(df["text"], df["direction"])
        with open(model_dir / "direction_model.pkl", "wb") as f:
            pickle.dump(pipe_dir, f)
        results["direction"] = True
    else:
        results["direction"] = False

    return results


__all__ = [
    "fetch_reddit_sync",
    "TransformerFakeDetector",
    "get_fake_detector",
    "classify_fake_transformer",
    "compute_cross_asset_correlation",
    "predict_multi_asset",
    "export_training_data",
    "retrain_ml_models",
]