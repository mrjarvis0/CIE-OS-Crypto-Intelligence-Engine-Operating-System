"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.fetch

Purpose:
    Data connectors — RSS (keyless) and API connectors (keyed).

Design goals:
    - Sync helpers explicitly marked; public API is async (asyncio.to_thread)
    - Every connector fails soft — agent runs in degraded mode without keys
    - No third-party HTTP client (stdlib urllib only)
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from agents.A02_News_Intelligence.config.settings import Settings
from agents.A02_News_Intelligence.config.sources import SOURCES

from .models import RawItem
from .normalize import parse_timestamp
from .phase7 import fetch_reddit_sync

_USER_AGENT = "Mozilla/5.0 (CIE-OS A02 News Intelligence Agent)"

# ==============================================================================
# KEYLESS RSS FEEDS (single source of truth: config.sources registry)
# ==============================================================================

RSS_FEEDS: tuple[tuple[str, str], ...] = tuple(
    (source.name, source.endpoint)
    for source in SOURCES
    if source.name.startswith("rss_")
)

# ==============================================================================
# SYNC HTTP HELPERS (explicitly sync — call via asyncio.to_thread)
# ==============================================================================


def http_get_sync(url: str, headers: dict[str, str] | None = None, timeout: float = 30.0) -> bytes:
    """Blocking GET. Returns raw bytes. Raises on HTTP errors."""

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# ==============================================================================
# RSS CONNECTOR
# ==============================================================================


def fetch_rss_sync(name: str, feed_url: str, limit: int, timeout: float) -> list[RawItem]:
    """Blocking RSS fetch and parse (ElementTree)."""

    payload = http_get_sync(feed_url, timeout=timeout)
    root = ET.fromstring(payload)
    items: list[RawItem] = []

    for entry in root.iter():
        if not (entry.tag.endswith("item") or entry.tag.endswith("entry")):
            continue
        if len(items) >= limit:
            break

        def _text(tag_name: str) -> str | None:
            for child in entry:
                if child.tag.endswith(tag_name):
                    return child.text
            return None

        title = _text("title") or ""
        link = _text("link")
        description = _text("description") or _text("summary") or ""
        published = parse_timestamp(_text("pubDate") or _text("published") or "")
        author = _text("creator") or _text("author") or None

        if not title:
            continue

        items.append(
            RawItem(
                source=name,
                source_key=f"{name}:{link or title}",
                url=link,
                title=title,
                content=description,
                author=author,
                published_at=published or datetime.now(UTC),
            )
        )
    return items


# ==============================================================================
# API CONNECTORS (keyed — return [] when key missing)
# ==============================================================================


def fetch_tiingo_sync(api_key: str, limit: int, timeout: float) -> list[RawItem]:
    """Blocking Tiingo news fetch."""

    url = f"https://api.tiingo.com/tiingo/news?token={api_key}&limit={limit}"
    payload = json.loads(http_get_sync(url, headers={"Content-Type": "application/json"}, timeout=timeout))
    items: list[RawItem] = []
    for article in payload:
        title = article.get("title") or ""
        if not title:
            continue
        items.append(
            RawItem(
                source="tiingo",
                source_key=f"tiingo:{article.get('id', title)}",
                url=article.get("url"),
                title=title,
                content=article.get("description") or "",
                author=article.get("source"),
                published_at=parse_timestamp(article.get("publishedDate")),
            )
        )
    return items


def fetch_newsapi_sync(api_key: str, limit: int, timeout: float) -> list[RawItem]:
    """Blocking NewsAPI fetch (finance query)."""

    url = (
        f"https://newsapi.org/v2/everything?q=finance&language=en"
        f"&pageSize={limit}&apiKey={api_key}"
    )
    payload = json.loads(http_get_sync(url, timeout=timeout))
    items: list[RawItem] = []
    for article in payload.get("articles", []):
        title = article.get("title") or ""
        if not title:
            continue
        items.append(
            RawItem(
                source="newsapi",
                source_key=f"newsapi:{article.get('url') or title}",
                url=article.get("url"),
                title=title,
                content=article.get("description") or article.get("content") or "",
                author=article.get("author"),
                published_at=parse_timestamp(article.get("publishedAt")),
            )
        )
    return items


# ==============================================================================
# PHASE 6: NEW CONNECTORS
# ==============================================================================


def fetch_telegram_sync(bot_token: str, chat_ids: list[str], limit: int, timeout: float) -> list[RawItem]:
    """Blocking Telegram bot API fetch (getUpdates)."""

    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {"limit": limit, "timeout": 10, "allowed_updates": '["message", "channel_post"]'}
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    payload = json.loads(http_get_sync(full_url, timeout=timeout))
    items: list[RawItem] = []
    for update in payload.get("result", []):
        message = update.get("message") or update.get("channel_post")
        if not message:
            continue
        chat_id = str(message.get("chat", {}).get("id"))
        if chat_ids and chat_id not in chat_ids:
            continue
        text = message.get("text") or message.get("caption") or ""
        if not text:
            continue
        msg_id = message.get("message_id")
        date = message.get("date")
        published = datetime.fromtimestamp(date, UTC) if date else datetime.now(UTC)
        sender = message.get("from", {}).get("username") or message.get("from", {}).get("first_name") or "unknown"
        items.append(
            RawItem(
                source="telegram",
                source_key=f"telegram:{chat_id}:{msg_id}",
                url=f"https://t.me/c/{chat_id}/{msg_id}" if chat_id.startswith("-100") else None,
                title=text[:120],
                content=text,
                author=sender,
                published_at=published,
            )
        )
    return items


def fetch_x_sync(bearer_token: str, query: str, limit: int, timeout: float) -> list[RawItem]:
    """Blocking X (Twitter) API v2 recent search."""

    url = "https://api.twitter.com/2/tweets/search/recent"
    params = {
        "query": query,
        "max_results": min(limit, 100),
        "tweet.fields": "created_at,author_id,public_metrics,source",
        "expansions": "author_id",
        "user.fields": "username",
    }
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    headers = {"Authorization": f"Bearer {bearer_token}"}
    payload = json.loads(http_get_sync(full_url, headers=headers, timeout=timeout))
    items: list[RawItem] = []
    users = {u["id"]: u["username"] for u in payload.get("includes", {}).get("users", [])}
    for tweet in payload.get("data", []):
        text = tweet.get("text", "")
        if not text:
            continue
        author_id = tweet.get("author_id")
        username = users.get(author_id, "unknown")
        created = tweet.get("created_at")
        published = parse_timestamp(created) or datetime.now(UTC)
        metrics = tweet.get("public_metrics", {})
        items.append(
            RawItem(
                source="x",
                source_key=f"x:{tweet.get('id')}",
                url=f"https://x.com/{username}/status/{tweet.get('id')}",
                title=text[:120],
                content=text,
                author=username,
                published_at=published,
                raw_json={
                    "retweet_count": metrics.get("retweet_count", 0),
                    "like_count": metrics.get("like_count", 0),
                    "reply_count": metrics.get("reply_count", 0),
                    "quote_count": metrics.get("quote_count", 0),
                },
            )
        )
    return items


# ==============================================================================
# AGGREGATION
# ==============================================================================

def _rss_source_names() -> set[str]:
    return {name for name, _ in RSS_FEEDS}


def _all_connectors(settings: Settings) -> list[tuple[str, str, callable]]:
    """Return (label, kind, callable) for every enabled connector."""

    connectors: list[tuple[str, str, callable]] = []
    for name, feed_url in RSS_FEEDS:
        connectors.append(
            (
                name,
                "rss",
                lambda name=name, feed_url=feed_url: fetch_rss_sync(
                    name, feed_url, settings.ingestion.max_items_per_fetch, settings.ingestion.request_timeout_seconds
                ),
            )
        )
    if settings.news.tiingo_api_key.get_secret_value():
        connectors.append(
            (
                "tiingo",
                "api",
                lambda: fetch_tiingo_sync(
                    settings.news.tiingo_api_key.get_secret_value(),
                    settings.ingestion.max_items_per_fetch,
                    settings.ingestion.request_timeout_seconds,
                ),
            )
        )
    if settings.news.newsapi_key.get_secret_value():
        connectors.append(
            (
                "newsapi",
                "api",
                lambda: fetch_newsapi_sync(
                    settings.news.newsapi_key.get_secret_value(),
                    settings.ingestion.max_items_per_fetch,
                    settings.ingestion.request_timeout_seconds,
                ),
            )
        )
    # Phase 6: Telegram
    if settings.social.telegram_bot_token.get_secret_value():
        chat_ids = [c.strip() for c in settings.social.telegram_chat_ids.split(",") if c.strip()]
        connectors.append(
            (
                "telegram",
                "api",
                lambda: fetch_telegram_sync(
                    settings.social.telegram_bot_token.get_secret_value(),
                    chat_ids,
                    settings.ingestion.max_items_per_fetch,
                    settings.ingestion.request_timeout_seconds,
                ),
            )
        )
    # Phase 6: X (Twitter)
    if settings.social.x_bearer_token.get_secret_value():
        connectors.append(
            (
                "x",
                "api",
                lambda: fetch_x_sync(
                    settings.social.x_bearer_token.get_secret_value(),
                    settings.social.x_search_query,
                    settings.ingestion.max_items_per_fetch,
                    settings.ingestion.request_timeout_seconds,
                ),
            )
        )
    # Phase 7: Reddit
    if settings.social.reddit_client_id.get_secret_value() and settings.social.reddit_client_secret.get_secret_value():
        subreddits = [s.strip() for s in settings.social.subreddits.split(",") if s.strip()]
        connectors.append(
            (
                "reddit",
                "api",
                lambda: fetch_reddit_sync(
                    settings.social.reddit_client_id.get_secret_value(),
                    settings.social.reddit_client_secret.get_secret_value(),
                    settings.social.reddit_user_agent,
                    subreddits,
                    settings.ingestion.max_items_per_fetch,
                    settings.ingestion.request_timeout_seconds,
                ),
            )
        )
    return connectors


async def fetch_all(settings: Settings, max_workers: int = 4) -> tuple[list[RawItem], list[str]]:
    """Fetch from every enabled connector concurrently (degraded mode OK)."""

    connectors = _all_connectors(settings)
    semaphore = asyncio.Semaphore(max_workers)

    async def run(label: str, fn: callable) -> list[RawItem]:
        async with semaphore:
            try:
                return await asyncio.to_thread(fn)
            except Exception as exc:  # soft fail — connector errors never kill the cycle
                return [RawItem(source=label, source_key=f"error:{label}", title=f"<connector error: {exc}>", content="")]

    results = await asyncio.gather(*(run(label, fn) for label, _, fn in connectors))
    items: list[RawItem] = []
    errors: list[str] = []
    for (label, _, _), batch in zip(connectors, results):
        if batch and batch[0].source == label and batch[0].source_key.startswith("error:"):
            errors.append(f"{label}: {batch[0].title}")
            continue
        items.extend(batch)
    return items, errors


__all__ = [
    "RSS_FEEDS",
    "http_get_sync",
    "fetch_rss_sync",
    "fetch_tiingo_sync",
    "fetch_newsapi_sync",
    "fetch_telegram_sync",
    "fetch_x_sync",
    "fetch_reddit_sync",
    "fetch_all",
]
