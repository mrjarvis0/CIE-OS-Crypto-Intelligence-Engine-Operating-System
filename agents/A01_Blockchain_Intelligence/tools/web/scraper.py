"""
Tools :: Web :: Scraper
=======================

Content scraping: URL fetching (with retry and proxy awareness),
robots validation and content extraction into structured page objects.
Local page store is the deterministic stand-in for live HTTP.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from ..utils.helpers import elapsed_ms
from .crawler import RobotsRules, canonicalize
from .parser import ParsedPage, WebParser

__all__ = ["ScrapeResult", "Scraper", "ScrapeCache"]


@dataclass
class ScrapeResult:
    """Outcome of one scrape attempt."""

    ok: bool
    url: str = ""
    page: Optional[ParsedPage] = None
    error: str = ""
    attempts: int = 0
    cached: bool = False
    duration_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "url": self.url,
            "page": self.page.as_dict() if self.page else None,
            "error": self.error,
            "attempts": self.attempts,
            "cached": self.cached,
            "duration_ms": round(self.duration_ms, 3),
        }


class ScrapeCache:
    """TTL cache keyed by canonical URL."""

    def __init__(self, ttl_s: float = 300.0) -> None:
        self.ttl_s = ttl_s
        self._entries: Dict[str, Dict[str, Any]] = {}

    def get(self, url: str) -> Optional[ParsedPage]:
        entry = self._entries.get(canonicalize(url))
        if entry is None:
            return None
        if time.time() - entry["fetched_at"] > self.ttl_s:
            self._entries.pop(canonicalize(url), None)
            return None
        return entry["page"]

    def set(self, url: str, page: ParsedPage) -> None:
        self._entries[canonicalize(url)] = {"page": page, "fetched_at": time.time()}

    def clear(self) -> None:
        self._entries.clear()

    def size(self) -> int:
        return len(self._entries)


class Scraper:
    """Fetches and parses pages with retries, robots checks and cache."""

    def __init__(
        self,
        *,
        fetch_fn: Optional[Callable[[str], str]] = None,
        store: Optional[Mapping[str, str]] = None,
        retries: int = 2,
        use_cache: bool = True,
        robots: Optional[RobotsRules] = None,
        user_agent: str = "cie-os/1.0",
        proxy: str = "",
    ) -> None:
        self.fetch_fn = fetch_fn
        self.store = dict(store or {})
        self.retries = max(0, int(retries))
        self.use_cache = use_cache
        self.robots = robots if robots is not None else RobotsRules()
        self.user_agent = user_agent
        self.proxy = proxy
        self.parser = WebParser()
        self.cache = ScrapeCache()

    def _fetch(self, url: str) -> str:
        if self.fetch_fn is not None:
            return self.fetch_fn(url)
        canonical = canonicalize(url)
        if canonical not in self.store:
            raise FileNotFoundError(f"no page available for {url!r}")
        return self.store[canonical]

    def scrape(self, url: str) -> ScrapeResult:
        started = time.perf_counter()
        canonical = canonicalize(url)

        if not self.robots.can_fetch(canonical):
            return ScrapeResult(ok=False, url=canonical, error="blocked by robots.txt", duration_ms=round(elapsed_ms(started), 3))

        if self.use_cache:
            cached = self.cache.get(canonical)
            if cached is not None:
                return ScrapeResult(ok=True, url=canonical, page=cached, cached=True, duration_ms=round(elapsed_ms(started), 3))

        attempts = 0
        while attempts <= self.retries:
            attempts += 1
            try:
                raw = self._fetch(canonical)
                page = self.parser.parse_page(raw, url=canonical)
                if self.use_cache:
                    self.cache.set(canonical, page)
                return ScrapeResult(ok=True, url=canonical, page=page, attempts=attempts, duration_ms=round(elapsed_ms(started), 3))
            except Exception as exc:  # noqa: BLE001 - retry then give up cleanly
                if attempts > self.retries:
                    return ScrapeResult(ok=False, url=canonical, error=f"{type(exc).__name__}: {exc}", attempts=attempts, duration_ms=round(elapsed_ms(started), 3))
        return ScrapeResult(ok=False, url=canonical, error="scrape failed", attempts=attempts, duration_ms=round(elapsed_ms(started), 3))