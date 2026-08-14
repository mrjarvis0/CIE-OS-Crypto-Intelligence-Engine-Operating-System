# A02 News Intelligence Agent — Tests

Offline test suites for each phase. Run directly with Python (no pytest config).

## Test Files

| File | Phase | Assertions | Coverage |
|------|-------|------------|----------|
| `test_core.py` | 1 | 38 | config, paths, sources, normalize, dedup, entities, storage, pipeline |
| `test_narrative.py` | 2 | 33 | claim extraction, clustering, stance, FOMO, lifecycle, coordination |
| `test_verification.py` | 3 | 28 | credibility tiers, source-level dedup, verdict logic, fabrication, manipulation |
| `test_impact.py` | 4 | 34 | returns, volatility, volume surge, category, history correlation, prediction |
| `test_learning.py` | 5 | 35 | metrics, Brier, calibration, verification report, drift, storage outcomes |
| `test_phase6.py` | 6 | 31 | ML models, extended categories, Telegram/X connectors, source tiers |
| `test_phase7.py` | 7 | 13 | Reddit connector, transformer fake detector, multi-asset correlation, retraining |

**Total: 212 assertions**

## Running Tests

```bash
# All tests
python agents/A02_News_Intelligence/tests/test_core.py
python agents/A02_News_Intelligence/tests/test_narrative.py
python agents/A02_News_Intelligence/tests/test_verification.py
python agents/A02_News_Intelligence/tests/test_impact.py
python agents/A02_News_Intelligence/tests/test_learning.py
python agents/A02_News_Intelligence/tests/test_phase6.py
python agents/A02_News_Intelligence/tests/test_phase7.py

# Or all at once
foreach ($t in @('test_core','test_narrative','test_verification','test_impact','test_learning','test_phase6','test_phase7')) {
    python agents/A02_News_Intelligence/tests/$t.py
}
```

## Test Design

- **No external dependencies** — use temp SQLite DBs, synthetic data
- **No pytest** — plain Python with simple `check(label, ok)` helper
- **Fast** — each suite < 2 seconds
- **Deterministic** — no network calls, fixed timestamps

## Adding Tests

Follow existing pattern:
```python
from agents.A02_News_Intelligence.module import function

def test_something():
    result = function(input)
    check("description", result == expected)

if __name__ == "__main__":
    test_something()
    print(f"RESULT: {PASS} passed, {FAIL} failed")
```