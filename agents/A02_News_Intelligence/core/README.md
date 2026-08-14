# A02 News Intelligence Agent — Core

Core ingestion, normalization, storage, and market data pipeline.

## Structure

```
core/
├── __init__.py          # exports main classes/functions
├── models.py            # Pydantic models: RawItem, NormalizedItem, Entity
├── normalize.py         # text cleaning, timestamp parsing, language detection
├── dedup.py             # fingerprinting (url/title/content), dedup logic
├── entities.py          # rule-based entity extraction (symbols, names)
├── pipeline.py          # main ingestion orchestration (fetch → normalize → store → narratives)
├── storage.py           # async SQLite repository (items, narratives, impact_events, scan_stats)
├── fetch.py             # data connectors (RSS, Tiingo, NewsAPI, Telegram, X, Reddit)
├── market.py            # market data (Binance klines, Alpha Vantage, SQLite caching)
├── symbols.py           # symbol registry (crypto/stocks/forex), entity type detection
├── phase7.py            # Phase 7: Reddit, transformer fake detector, multi-asset correlation, retraining
```

## Key Classes

### `Storage` (`storage.py`)
Async SQLite repository. Main methods:
- `insert_item(item)` / `count_items()` / `recent_items()`
- `insert_narrative(data)` / `load_active_narratives(since)` / `update_narrative()`
- `insert_impact_event(data)` / `load_impact_events()` / `resolve_impact_event()` / `load_unresolved_impact_events()`
- `insert_scan_stat(data)` / `load_scan_stats()`
- Auto-migrates schema on init (adds Phase 3/5/6/7 columns)

### `MarketData` (`market.py`)
- `fetch_and_store(symbol)` — fetches Binance klines, stores in `market_prices`
- `series_around(symbol, t0, hours_before, hours_after)` — candles around timestamp
- `last_close(symbol)` — most recent close price

### `fetch.py` Connectors
All connectors are sync helpers called via `asyncio.to_thread`:
- `fetch_rss_sync(name, feed_url, limit, timeout)` — RSS/Atom via ElementTree
- `fetch_tiingo_sync(api_key, limit, timeout)` — Tiingo news API
- `fetch_newsapi_sync(api_key, limit, timeout)` — NewsAPI finance query
- `fetch_telegram_sync(bot_token, chat_ids, limit, timeout)` — Telegram getUpdates
- `fetch_x_sync(bearer_token, query, limit, timeout)` — X API v2 recent search
- `fetch_reddit_sync(client_id, client_secret, user_agent, subreddits, limit, timeout)` — Reddit public listing
- `fetch_all(settings)` — runs all enabled connectors concurrently, returns (items, errors)

All connectors fail soft — agent runs in degraded mode without API keys.

## Pipeline

`pipeline.ingest(settings)` runs one full cycle:
1. Fetch from all connectors
2. Normalize (clean text, parse timestamps, extract entities)
3. Dedup (url fingerprint → title fingerprint → content fingerprint)
4. Store items
4. Build/update narratives (clustering, stance, FOMO, verification, coordination)
5. Return `IngestReport` with counts

## Usage

```python
from agents.A02_News_Intelligence.config import get_settings
from agents.A02_News_Intelligence.core.pipeline import ingest

settings = get_settings()
report = await ingest(settings)
print(f"stored={report.stored}, narratives={report.narratives}")
```