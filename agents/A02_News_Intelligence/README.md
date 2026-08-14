# A02 News Intelligence Agent

**Project:** CIE-OS (Crypto Intelligence Engine Operating System)
**Status:** Phase 0 (Foundation) — in progress
**Mission:** Detect, track and verify fake news/rumors in financial markets, and predict their impact on stocks, crypto and forex.

## Phases

| Phase | Content | Status |
|---|---|---|
| 0 | Foundation — structure, config, env, CLI stub | ✅ |
| 1 | Data sources + ingestion + normalization + dedup + entity extraction + storage | ✅ |
| 2 | Narrative intelligence — claims, clustering, stance, propagation, FOMO | ✅ |
| 3 | Verification + manipulation — evidence, source hierarchy, coordination | ✅ |
| 4 | Market impact + prediction — rules → ML, historical correlation | ✅ |
| 5 | Learning + backtest — outcomes, calibration, drift, output interface | ✅ |
| 6 | ML models, extended categories, Telegram/X connectors | ✅ |
| 7 | Reddit connector, transformer fake detector, multi-asset correlation, retraining utils | ✅ |

## Structure (minimal by design)

```
A02_News_Intelligence/
├── config/          # settings (env A02_), paths, constants, source registry
├── core/            # ingestion, normalization, storage
├── intelligence/    # narrative, verification, manipulation, impact
├── models/          # saved trained models
├── data/            # raw / processed / outcomes
└── cli/             # main.py — doctor, scan, backtest
```

## Key rules

- **No `FAKE`/`REAL` binary output.** Signature output = evidence + epistemic status + confidence + impact range + uncertainty.
- **FOMO ≠ Truth ≠ Coordination.** These are separate scores, never merged into one.
- **Low false positive rate is the flagship goal** (ref. FinFakeBERT ≈2.1% FPR).
- 10 articles copying 1 original tweet ≠ 10 confirmations — dedup at source level.
- Predictions always as probability + range + confidence, never certainty.
- Env vars use `A02_` prefix; all keys optional (degraded mode without keys).

## Commands

```bash
python -m agents.A02_News_Intelligence.cli doctor       # validate foundation
python -m agents.A02_News_Intelligence.cli scan         # one ingestion + narrative + verification cycle (+ drift snapshot)
python -m agents.A02_News_Intelligence.cli narratives   # active narratives ranked by FOMO (verdict + coordination)
python -m agents.A02_News_Intelligence.cli impact <id>  # market impact prediction for a narrative (live price fetch)
python -m agents.A02_News_Intelligence.cli resolve      # resolve open predictions against live price (learning loop)
python -m agents.A02_News_Intelligence.cli metrics      # accuracy, Brier, calibration bins, drift summary
python -m agents.A02_News_Intelligence.cli backtest     # replay resolved predictions vs actual outcomes
python -m agents.A02_News_Intelligence.cli output <id>  # flagship 12-point consumer report
python agents/A02_News_Intelligence/tests/test_core.py       # Phase 1 offline tests (38 assertions)
python agents/A02_News_Intelligence/tests/test_narrative.py  # Phase 2 offline tests (33 assertions)
python agents/A02_News_Intelligence/tests/test_verification.py  # Phase 3 offline tests (28 assertions)
python agents/A02_News_Intelligence/tests/test_impact.py     # Phase 4 offline tests (34 assertions)
python agents/A02_News_Intelligence/tests/test_learning.py   # Phase 5 offline tests (35 assertions)
python agents/A02_News_Intelligence/tests/test_phase6.py     # Phase 6 offline tests (31 assertions)
python agents/A02_News_Intelligence/tests/test_phase7.py     # Phase 7 offline tests (13 assertions)
```

## Pipeline

```
news/social/market → ingestion → normalization → dedup → entity extraction
→ storage → narrative (claims/cluster/stance/propagation/FOMO)
→ verification (evidence/verdict/confidence) → manipulation (coordination)
→ impact prediction → resolve (outcome capture) → metrics (accuracy/Brier/
calibration) → backtest → output (12-point report)
```

## Phase 5 additions

- **Learning loop**: every `impact` stores a prediction snapshot (direction,
  probability, mean return); `resolve` records the realized outcome against
  live price; `metrics` turns those into accuracy, Brier score and calibration
  bins (overconfident bins flagged).
- **Drift monitoring**: each `scan` stores a verdict-distribution snapshot;
  `metrics` shows the latest verdict mix as a false-positive drift watch.
- **Backtest**: replays all resolved predictions as a hit table with a naive
  majority-class baseline comparison.
- **Final output**: `output <id>` — the 12-point consumer report: claim,
  affected assets, spread, FOMO, manipulation risk, evidence, epistemic status,
  confidence, market reaction, historical analog, impact prediction, next
  confirmation/debunk signal.

## Phase 7 additions

- **Reddit connector** (`core/fetch.py`): public read-only listing via `www.reddit.com/r/<sub>/new.json` — enabled via `A02_SOCIAL_REDDIT_CLIENT_ID` + `A02_SOCIAL_REDDIT_CLIENT_SECRET`.
- **Transformer fake detector** (`core/phase7.py`): Hugging Face `pipeline` framework with rule fallback — loads fine-tuned model if available, otherwise uses fabrication-marker rules.
- **Multi-asset correlation** (`core/phase7.py`): Pearson correlation of historical returns across assets; `predict_multi_asset()` propagates primary prediction to correlated assets (direction/probability/expected return scaled by correlation).
- **Retraining utilities** (`core/phase7.py`): `export_training_data()` exports resolved events as labeled JSON; `retrain_ml_models()` retrains category/verification/direction models from exported data.
