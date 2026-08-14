"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.market

Purpose:
    Market price data connector + candle storage (Phase 4).

Design goals:
    - Async-first (asyncio.to_thread); sync helpers marked explicitly
    - Binance klines for crypto (keyless); Alpha Vantage for stocks/forex (keyed)
    - Soft-fail — missing keys/network never break the pipeline
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from .fetch import http_get_sync
from .storage import Storage


class MarketData:
    """Fetches and stores OHLCV candles, serves price series from SQLite."""

    def __init__(
        self,
        storage: Storage,
        binance_base_url: str = "https://api.binance.com",
        alpha_vantage_key: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.storage = storage
        self.binance_base_url = binance_base_url
        self.alpha_vantage_key = alpha_vantage_key
        self.timeout = timeout

    # ==========================================================================
    # SYNC FETCHERS (explicitly sync)
    # ==========================================================================

    def fetch_binance_klines_sync(self, symbol: str, interval: str = "1h", limit: int = 200) -> list[dict]:
        """Blocking Binance kline fetch. Candle keys: open_time, o/h/l/c, volume."""

        pair = f"{symbol.upper()}USDT"
        url = f"{self.binance_base_url}/api/v3/klines?symbol={pair}&interval={interval}&limit={limit}"
        payload = json.loads(http_get_sync(url, timeout=self.timeout))
        candles = []
        for row in payload:
            candles.append(
                {
                    "open_time": datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        return candles

    def fetch_alpha_vantage_sync(self, symbol: str, interval: str = "60min") -> list[dict]:
        """Blocking Alpha Vantage intraday fetch for stocks/forex."""

        url = (
            f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY"
            f"&symbol={symbol}&interval={interval}&outputsize=compact&apikey={self.alpha_vantage_key}"
        )
        payload = json.loads(http_get_sync(url, timeout=self.timeout))
        series = payload.get(f"Time Series ({interval})", {})
        candles = []
        for timestamp, values in series.items():
            candles.append(
                {
                    "open_time": datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(UTC),
                    "open": float(values["1. open"]),
                    "high": float(values["2. high"]),
                    "low": float(values["3. low"]),
                    "close": float(values["4. close"]),
                    "volume": float(values.get("5. volume") or 0),
                }
            )
        return candles

    # ==========================================================================
    # ASYNC API
    # ==========================================================================

    async def fetch_and_store(self, symbol: str, interval: str = "1h", limit: int = 200) -> int:
        """Fetch candles and upsert into market_prices. Returns stored count (0 on failure)."""

        try:
            candles = await asyncio.to_thread(
                self.fetch_binance_klines_sync, symbol, interval, limit
            )
        except Exception:
            return 0
        if not candles:
            return 0
        async with __import__("aiosqlite").connect(self.storage.db_path) as db:
            for candle in candles:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO market_prices
                        (symbol, interval, open_time, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol.upper(),
                        interval,
                        candle["open_time"].isoformat(),
                        candle["open"],
                        candle["high"],
                        candle["low"],
                        candle["close"],
                        candle["volume"],
                    ),
                )
            await db.commit()
        return len(candles)

    async def series_around(
        self, symbol: str, t0: datetime, hours_before: int = 48, hours_after: int = 48
    ) -> list[dict]:
        """Candles for symbol within [t0 - hours_before, t0 + hours_after]."""

        start = (t0 - timedelta(hours=hours_before)).isoformat()
        end = (t0 + timedelta(hours=hours_after)).isoformat()
        async with __import__("aiosqlite").connect(self.storage.db_path) as db:
            db.row_factory = __import__("aiosqlite").Row
            cursor = await db.execute(
                """
                SELECT * FROM market_prices
                WHERE symbol = ? AND interval = '1h' AND open_time >= ? AND open_time <= ?
                ORDER BY open_time
                """,
                (symbol.upper(), start, end),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def last_close(self, symbol: str) -> float | None:
        """Most recent close price for a symbol (for display)."""

        async with __import__("aiosqlite").connect(self.storage.db_path) as db:
            db.row_factory = __import__("aiosqlite").Row
            cursor = await db.execute(
                "SELECT close FROM market_prices WHERE symbol = ? ORDER BY open_time DESC LIMIT 1",
                (symbol.upper(),),
            )
            row = await cursor.fetchone()
            return float(row["close"]) if row else None


__all__ = ["MarketData"]
