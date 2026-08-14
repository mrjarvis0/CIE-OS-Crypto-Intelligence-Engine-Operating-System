# A02 Training Package

Curated labeled dataset + evaluation harness for the verification engine.

## Files

- `dataset.py` — 41 labeled samples (13 real, 15 fake, 13 complex) with expected epistemic verdicts
- `evaluate.py` — Harness that rebuilds Narratives, runs `verify_narrative`, classifies HIT/WEAK/FP/FN

## Usage

```bash
# Rules-only evaluation (default)
python -m agents.A02_News_Intelligence.training.evaluate

# Single sample debug
python -m agents.A02_News_Intelligence.training.evaluate --name fake_etf_tweet_coordination
```

## Sample Groups

| Group | Count | Expected Verdicts |
|-------|-------|-------------------|
| real | 13 | likely_true, confirmed_true |
| fake | 15 | fabricated, likely_false, confirmed_false |
| complex | 13 | unconfirmed, disputed, likely_true, confirmed_true |

## Classification

- **HIT**: verdict matches expected (or same leaning)
- **WEAK**: indecisive on ambiguous data (not wrong)
- **FP**: real news flagged as false/fabricated — **must be 0**
- **FN**: fake news accepted as true — **must be 0**

## Current Status

All 41 samples: HIT=41, WEAK=0, FP=0, FN=0 ✓

All 7 test suites (212 assertions): PASS ✓