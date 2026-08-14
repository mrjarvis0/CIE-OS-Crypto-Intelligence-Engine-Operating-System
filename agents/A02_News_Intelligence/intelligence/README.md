# A02 News Intelligence Agent — Intelligence

Narrative building, verification, manipulation detection, impact prediction, and learning.

## Structure

```
intelligence/
├── __init__.py          # exports all public functions
├── narrative.py         # Narrative model + engine (clustering, claims, stance, FOMO, lifecycle)
├── claims.py            # claim extraction from title/content + entities
├── cluster.py           # title Jaccard + entity overlap clustering (0.5x penalty for no shared entity)
├── stance.py            # stance classification (support/deny/neutral/question) — rules + ML
├── verification.py      # verification (credibility tiers, source-level dedup, 7-tier verdict + confidence)
├── manipulation.py      # coordination score (identical text, timing burst, author/platform concentration)
├── history.py           # category classification (21 categories) + historical correlation engine
├── impact.py            # event-study returns (1h/6h/24h), volatility, volume surge, severity
├── predict.py           # AssetPrediction: direction + probability + range + historical analog + risk
├── learning.py          # Phase 5: metrics (accuracy, Brier, calibration), verification report, drift
```

## Narrative Engine (`narrative.py`)

`NarrativeEngine(window_hours=24, min_mentions=3, match_threshold=0.22)`

- `update(storage, items, now)` — processes new items, builds/updates narratives
- Clustering: title Jaccard + entity overlap; no-shared-entity titles penalized 0.5x
- Stance: deny > support > question > neutral (rules + ML)
- FOMO: velocity + sources + platforms + urgency
- Lifecycle: emerging → spreading → peak_hype → verifying → resolved
- Verification: 7-tier epistemic status + confidence 0-1
- Coordination: 0-100 score (identical text ratio, timing burst, author/platform concentration)

## Verification (`verification.py`)

Evidence hierarchy (lower = more credible):
1. Official (sec.gov, binance.com, etc.)
2. Established media (Reuters, Bloomberg, CNBC, etc.)
3. Crypto media (CoinDesk, CoinTelegraph, etc.)
4. Aggregators (Tiingo, NewsAPI, Yahoo Finance)
5. Social (Reddit, X, Telegram)
6. Anonymous

Source-level dedup: items sharing content fingerprint = 1 underlying source

Verdict logic (priority order):
1. Fabricated markers → `fabricated`
2. ≥2 denies → `confirmed_false` (official deny = stronger)
3. 1 deny, 0 support → `likely_false`
4. 1 deny + support → `disputed`
5. ≥2 official → `confirmed_true`
6. 1 official → `likely_true`
7. ≥2 support + ≥2 credible → `likely_true`
8. ≥1 support + ≥1 credible → `unconfirmed`
9. ≥3 questions → `unconfirmed`
10. Default → `unconfirmed`

ML signal (Phase 6): used as additional signal alongside rules

## Impact & Prediction

`impact.py`: event-study around narrative `first_seen`
- Returns at 1h/6h/24h horizons
- Volatility (24h window)
- Volume surge (6h window)
- Severity: flat/mild/moderate/severe

`history.py`: category classification (21 categories, specific before general)
- Historical correlation: finds similar past events by category + FOMO bucket + asset
- Expected impact: weighted mean/range from analogs

`predict.py`: combines measured + historical + verification → `AssetPrediction`
- direction: up/down/flat
- probability: 0-1
- expected_low/high/mean_pct: range
- historical_similarity, events_used, main_risk

## Learning (`learning.py`)

- `metrics(events)` — accuracy, Brier, MAE, bias, calibration bins
- `calibration(events)` — per-probability-bin honesty check (overconfident flag)
- `verification_report(events)` — verdict vs truth agreement
- `drift_report(stats)` — per-scan verdict distribution trend

## Usage

```python
from agents.A02_News_Intelligence.intelligence.narrative import NarrativeEngine
from agents.A02_News_Intelligence.core.storage import Storage

engine = NarrativeEngine()
narratives = await engine.update(storage, items, datetime.now(UTC))
```