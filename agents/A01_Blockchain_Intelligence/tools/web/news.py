"""
Tools :: Web :: News
====================

News search: syndicated sources, headline lookup and trending topic
detection over a local news corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .rss import RSSClient, RSSItem
from .search import SearchDocument, SearchResult, WebSearch

__all__ = ["NewsArticle", "NewsSource", "NewsSearch", "NewsClient"]

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class NewsArticle:
    """A normalized news article."""

    headline: str
    url: str = ""
    summary: str = ""
    source: str = ""
    published: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "headline": self.headline,
            "url": self.url,
            "summary": self.summary,
            "source": self.source,
            "published": self.published,
        }


@dataclass
class NewsSource:
    """A news outlet registered with the search."""

    name: str
    url: str = ""
    topics: List[str] = field(default_factory=list)


class NewsSearch:
    """Searches a local news corpus; sources are registered locally."""

    def __init__(self) -> None:
        self._index = WebSearch()
        self._sources: Dict[str, NewsSource] = {}

    def register_source(self, source: NewsSource) -> None:
        self._sources[source.name] = source

    def add_article(self, article: NewsArticle) -> None:
        self._index.index(
            SearchDocument(
                url=article.url,
                title=article.headline,
                content=article.summary,
                source=article.source or "news",
                published=article.published,
            )
        )

    def search(self, query: str, *, limit: int = 10) -> List[SearchResult]:
        return self._index.search(query, limit=limit)

    def latest(self, limit: int = 10) -> List[SearchResult]:
        return self._index.search("", limit=limit)

    def trending(self, limit: int = 5) -> List[str]:
        """Most frequent tokens across recent headlines."""
        counts: Dict[str, int] = {}
        for document in self._index._documents.values():
            for token in _WORD_RE.findall(document.title.lower()):
                if len(token) > 3:
                    counts[token] = counts.get(token, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return [token for token, _ in ranked[: max(1, int(limit))]]

    def sources(self) -> List[NewsSource]:
        return list(self._sources.values())


class NewsClient:
    """High-level news facade: RSS feeds + corpus search."""

    def __init__(self) -> None:
        self.rss = RSSClient()
        self.search = NewsSearch()
        self._feed_sources: Dict[str, str] = {}

    def subscribe(self, feed_url: str, raw_xml: str, *, source_name: str = "") -> None:
        self.rss.subscribe(feed_url, raw_xml)
        self._feed_sources[feed_url] = source_name
        if source_name:
            self.search.register_source(NewsSource(name=source_name, url=feed_url))

    def ingest_feeds(self) -> int:
        """Pull all subscribed feeds into the searchable corpus."""
        count = 0
        for feed_url in self.rss.subscribed():
            try:
                feed = self.rss.fetch(feed_url)
            except (KeyError, ValueError):
                continue
            source = self._feed_sources.get(feed_url, "")
            for item in feed.items:
                article = NewsArticle(headline=item.title, url=item.link, summary=item.description, source=source or feed.title, published=item.published)
                self.search.add_article(article)
                count += 1
        return count