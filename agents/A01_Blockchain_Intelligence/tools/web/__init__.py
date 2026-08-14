"""
Tools :: Web Layer
==================

Internet intelligence and retrieval subsystem of CIE-OS: search,
discovery, fetch, crawl, scrape, parse, verify, cache and structure
information from the public web. The web layer never reasons; it only
retrieves, cleans, validates and prepares high-quality web context.

Modules: search, news, crawler, scraper, parser, rss, browser.
:class:`WebClient` is the facade.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

__all__ = [
    "WebError",
    "SearchResult",
    "SearchDocument",
    "QueryBuilder",
    "WebSearch",
    "NewsArticle",
    "NewsSource",
    "NewsSearch",
    "NewsClient",
    "RSSItem",
    "RSSFeed",
    "parse_rss",
    "RSSClient",
    "CrawlJob",
    "CrawlStats",
    "RobotsRules",
    "Sitemap",
    "Crawler",
    "canonicalize",
    "ScrapeResult",
    "ScrapeCache",
    "Scraper",
    "ParseResult",
    "ParsedPage",
    "strip_tags",
    "extract_title",
    "extract_meta",
    "extract_links",
    "extract_text",
    "markdown_from_html",
    "parse_json",
    "parse_xml",
    "parse_structured_data",
    "WebParser",
    "Cookie",
    "PageSnapshot",
    "BrowserSession",
    "Browser",
    "WebClient",
]


class WebError(Exception):
    """Base class for every error raised by the web layer."""


from .search import SearchResult, SearchDocument, QueryBuilder, WebSearch  # noqa: E402
from .news import NewsArticle, NewsSource, NewsSearch, NewsClient  # noqa: E402
from .rss import RSSItem, RSSFeed, parse_rss, RSSClient  # noqa: E402
from .crawler import CrawlJob, CrawlStats, RobotsRules, Sitemap, Crawler, canonicalize  # noqa: E402
from .scraper import ScrapeResult, ScrapeCache, Scraper  # noqa: E402
from .parser import (  # noqa: E402
    ParseResult,
    ParsedPage,
    strip_tags,
    extract_title,
    extract_meta,
    extract_links,
    extract_text,
    markdown_from_html,
    parse_json,
    parse_xml,
    parse_structured_data,
    WebParser,
)
from .browser import Cookie, PageSnapshot, BrowserSession, Browser  # noqa: E402


class WebClient:
    """Unified web intelligence facade: search -> fetch -> parse ->
    verify -> cache."""

    def __init__(self, store: Optional[Mapping[str, str]] = None) -> None:
        self.store = dict(store or {})
        self.search = WebSearch()
        self.news = NewsClient()
        self.crawler = Crawler(fetch_fn=self._fetch_for_crawl)
        self.scraper = Scraper(store=self.store)
        self.browser = Browser(store=self.store)

    def _fetch_for_crawl(self, url: str) -> str:
        result = self.scraper.scrape(url)
        if not result.ok or result.page is None:
            raise FileNotFoundError(result.error or "fetch failed")
        return result.page.html or result.page.text

    def index_page(self, url: str, title: str, content: str) -> None:
        self.search.index(SearchDocument(url=url, title=title, content=content))

    def query(self, text: str, *, limit: int = 10) -> list:
        return self.search.search(text, limit=limit)