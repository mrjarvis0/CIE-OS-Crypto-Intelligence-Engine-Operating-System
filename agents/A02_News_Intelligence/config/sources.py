"""
CIE-OS
A02 News Intelligence Agent

Module:
    config.sources

Purpose:
    Registry of data sources (news, social, market) with default endpoints.

Design goals:
    - Static metadata only — no network calls
    - Phase 1 ingestion will consume this registry
    - Adding a source = adding one entry
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# ==============================================================================
# SOURCE KIND
# ==============================================================================

NEWS_SOURCE: Final[str] = "news"
SOCIAL_SOURCE: Final[str] = "social"
MARKET_SOURCE: Final[str] = "market"


@dataclass(frozen=True)
class SourceDefinition:
    """Static definition of a data source."""

    name: str
    kind: str
    endpoint: str
    enabled: bool = True
    requires_key: bool = False
    supported: tuple[str, ...] = field(default_factory=tuple)


# ==============================================================================
# REGISTRY
# ==============================================================================

SOURCES: tuple[SourceDefinition, ...] = (
    # --- News / web -----------------------------------------------------------
    SourceDefinition(
        name="tiingo",
        kind=NEWS_SOURCE,
        endpoint="https://api.tiingo.com/tiingo/news",
        requires_key=True,
        supported=("stocks", "crypto", "forex"),
    ),
    SourceDefinition(
        name="alpaca_news",
        kind=NEWS_SOURCE,
        endpoint="https://data.alpaca.markets/v1beta1/news",
        requires_key=True,
        supported=("stocks",),
    ),
    SourceDefinition(
        name="finnhub",
        kind=NEWS_SOURCE,
        endpoint="https://finnhub.io/api/v1/company-news",
        requires_key=True,
        supported=("stocks",),
    ),
    SourceDefinition(
        name="newsapi",
        kind=NEWS_SOURCE,
        endpoint="https://newsapi.org/v2/everything",
        requires_key=True,
        supported=("stocks", "crypto", "forex"),
    ),
    SourceDefinition(
        name="financialjuice",
        kind=NEWS_SOURCE,
        endpoint="wss://stream.financialjuice.com",
        requires_key=True,
        supported=("forex", "macro"),
    ),
    # --- RSS (keyless, free) ----------------------------------------------------
    SourceDefinition(
        name="rss_cnbc",
        kind=NEWS_SOURCE,
        endpoint="https://www.cnbc.com/id/100003114/device/rss/rss.html",
    ),
    SourceDefinition(
        name="rss_marketwatch",
        kind=NEWS_SOURCE,
        endpoint="https://feeds.content.dowjones.io/public/rss/mw_topstories",
    ),
    SourceDefinition(
        name="rss_coindesk",
        kind=NEWS_SOURCE,
        endpoint="https://www.coindesk.com/arc/outboundfeeds/rss/",
    ),
    SourceDefinition(
        name="rss_cointelegraph",
        kind=NEWS_SOURCE,
        endpoint="https://cointelegraph.com/rss",
    ),
    SourceDefinition(
        name="rss_yahoo_finance",
        kind=NEWS_SOURCE,
        endpoint="https://finance.yahoo.com/news/rssindex",
    ),
    # --- Social ----------------------------------------------------------------
    SourceDefinition(
        name="reddit",
        kind=SOCIAL_SOURCE,
        endpoint="https://oauth.reddit.com",
        requires_key=True,
        supported=("stocks", "crypto"),
    ),
    SourceDefinition(
        name="x_stream",
        kind=SOCIAL_SOURCE,
        endpoint="https://api.x.com/2/tweets/search/stream",
        requires_key=True,
        supported=("stocks", "crypto", "forex"),
    ),
    # --- Market ----------------------------------------------------------------
    SourceDefinition(
        name="alpha_vantage",
        kind=MARKET_SOURCE,
        endpoint="https://www.alphavantage.co/query",
        requires_key=True,
        supported=("stocks", "crypto", "forex"),
    ),
    SourceDefinition(
        name="binance",
        kind=MARKET_SOURCE,
        endpoint="https://api.binance.com/api/v3/klines",
        requires_key=False,
        supported=("crypto",),
    ),
)


def get_source(name: str) -> SourceDefinition | None:
    """Return source definition by name or None."""

    return next((s for s in SOURCES if s.name == name), None)


def sources_by_kind(kind: str) -> tuple[SourceDefinition, ...]:
    """Return all sources of the given kind."""

    return tuple(s for s in SOURCES if s.kind == kind)


__all__ = [
    "NEWS_SOURCE",
    "SOCIAL_SOURCE",
    "MARKET_SOURCE",
    "SourceDefinition",
    "SOURCES",
    "get_source",
    "sources_by_kind",
]
