# A02 News Intelligence Agent — CLI

Command-line interface for the A02 agent.

## Commands

```bash
# Foundation
python -m agents.A02_News_Intelligence.cli doctor       # validate paths, settings, sources, DB schema

# Ingestion & Narratives
python -m agents.A02_News_Intelligence.cli scan         # one full cycle: fetch → normalize → dedup → narratives (+ drift snapshot)
python -m agents.A02_News_Intelligence.cli narratives   # active narratives ranked by FOMO (verdict + coordination)

# Market Impact & Learning
python -m agents.A02_News_Intelligence.cli impact <id>  # market impact prediction for narrative (live Binance fetch)
python -m agents.A02_News_Intelligence.cli resolve      # resolve open predictions against live price (--all or <event_id>)
python -m agents.A02_News_Intelligence.cli metrics      # accuracy, Brier, calibration bins, verification agreement, drift
python -m agents.A02_News_Intelligence.cli backtest     # replay resolved predictions vs naive baseline

# Flagship Output
python -m agents.A02_News_Intelligence.cli output <id>  # 12-point consumer report
```

## Output Command (12-Point Report)

```bash
python -m agents.A02_News_Intelligence.cli output 19
```

Output sections:
1. **CLAIM** — full claim text
2. **AFFECTED ASSETS** — entity symbols
3. **SPREAD** — mentions, sources, platforms, velocity, status, first_seen
4. **FOMO** — score 0-100 + tier (extreme/elevated/mild)
5. **MANIPULATION RISK** — coordination score + flags
6. **EVIDENCE** — underlying_sources, items, official_sources, credible_sources, social_only, stance counts
7. **EPISTEMIC STATUS** — 7-tier verdict
8. **CONFIDENCE** — 0-100%
9. **MARKET REACTION** — measured returns (1h/6h/24h), volatility, volume surge
10. **HISTORICAL ANALOG** — category, similarity, events_used, risk
11. **IMPACT PREDICTION** — direction, probability, range, mean
12. **NEXT SIGNAL** — what to watch for confirmation/debunk

## Resolve Command

```bash
# Resolve all unresolved predictions
python -m agents.A02_News_Intelligence.cli resolve --all

# Resolve specific event
python -m agents.A02_News_Intelligence.cli resolve 3
```

Fetches live price, computes actual return from `first_seen` to now, updates `impact_events`.

## Metrics Command

Shows:
- Resolved count, direction accuracy, Brier score
- Mean absolute impact error, signed bias
- Calibration bins (mean predicted vs actual hit rate, overconfident flag)
- Verification truth agreement
- Drift: latest scan verdict distribution

## Backtest Command

Replays all resolved events:
- Per-event table: predicted vs actual, HIT/miss
- Aggregate accuracy vs naive majority-class baseline
- Mean absolute impact error

## Entry Point

`cli/main.py` — uses `argparse` with subcommands. All commands are async via `asyncio.run()`.