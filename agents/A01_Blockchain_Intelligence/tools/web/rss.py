"""
Tools :: Web :: RSS
===================

RSS feed parsing and syndication clients. Parses RSS 2.0 / Atom XML with
stdlib xml.etree; local feeds are the deterministic stand-in for live
internet access.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..utils.helpers import iso_now
from .parser import ParseResult, parse_xml

__all__ = ["RSSItem", "RSSFeed", "parse_rss", "RSSClient"]

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


def _q(name: str) -> str:
    if ":" in name:
        prefix, local = name.split(":", 1)
        return f"{{{_NS[prefix]}}}{local}"
    return name


@dataclass
class RSSItem:
    """One syndicated feed entry."""

    title: str
    link: str = ""
    description: str = ""
    guid: str = ""
    published: str = ""
    author: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "link": self.link,
            "description": self.description,
            "guid": self.guid,
            "published": self.published,
            "author": self.author,
        }


@dataclass
class RSSFeed:
    """Parsed feed with its items."""

    title: str = ""
    link: str = ""
    description: str = ""
    items: List[RSSItem] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "link": self.link,
            "description": self.description,
            "items": [item.as_dict() for item in self.items],
        }


def parse_rss(raw: str) -> ParseResult:
    """Parse an RSS/Atom document into an :class:`RSSFeed`."""
    parsed = parse_xml(raw)
    if not parsed.ok:
        return parsed
    root: ET.Element = parsed.data
    feed = RSSFeed()
    channel = root if root.tag == "channel" else root.find("channel")
    if channel is not None:
        feed.title = (channel.findtext("title") or "").strip()
        feed.link = (channel.findtext("link") or "").strip()
        feed.description = (channel.findtext("description") or "").strip()
        for item_el in channel.findall("item"):
            feed.items.append(
                RSSItem(
                    title=(item_el.findtext("title") or "").strip(),
                    link=(item_el.findtext("link") or "").strip(),
                    description=(item_el.findtext("description") or "").strip(),
                    guid=(item_el.findtext("guid") or "").strip(),
                    published=(item_el.findtext("pubDate") or "").strip(),
                    author=(item_el.findtext("author") or item_el.findtext(_q("dc:creator")) or "").strip(),
                )
            )
        return ParseResult(ok=True, data=feed)
    if root.tag == _q("atom:feed"):
        feed.title = (root.findtext(_q("atom:title")) or "").strip()
        feed.link = (root.findtext(_q("atom:link")) or "").strip()
        for entry in root.findall(_q("atom:entry")):
            feed.items.append(
                RSSItem(
                    title=(entry.findtext(_q("atom:title")) or "").strip(),
                    link=(entry.findtext(_q("atom:link")) or "").strip(),
                    description=(entry.findtext(_q("atom:summary")) or entry.findtext(_q("atom:content")) or "").strip(),
                    guid=(entry.findtext(_q("atom:id")) or "").strip(),
                    published=(entry.findtext(_q("atom:updated")) or entry.findtext(_q("atom:published")) or "").strip(),
                    author=(entry.findtext(_q("atom:author") + "/" + _q("atom:name")) or "").strip(),
                )
            )
        return ParseResult(ok=True, data=feed)
    return ParseResult(ok=False, error="unknown feed format")


class RSSClient:
    """Syndication client backed by a local feed registry. Real network
    backends subclass and override ``_fetch_feed``."""

    def __init__(self) -> None:
        self._feeds: Dict[str, str] = {}

    def subscribe(self, feed_url: str, raw_xml: str) -> None:
        self._feeds[feed_url] = raw_xml

    def fetch(self, feed_url: str) -> RSSFeed:
        raw = self._feeds.get(feed_url)
        if raw is None:
            raise KeyError(f"feed {feed_url!r} not subscribed")
        parsed = parse_rss(raw)
        if not parsed.ok:
            raise ValueError(parsed.error)
        return parsed.data

    def subscribed(self) -> List[str]:
        return list(self._feeds)

    def latest_items(self, limit: int = 20) -> List[RSSItem]:
        items: List[RSSItem] = []
        for feed_url in self._feeds:
            try:
                items.extend(self.fetch(feed_url).items)
            except (KeyError, ValueError):
                continue
        items.sort(key=lambda item: item.published, reverse=True)
        return items[: max(1, int(limit))]