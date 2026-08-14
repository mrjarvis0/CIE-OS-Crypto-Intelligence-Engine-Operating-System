"""
Tools :: Web :: Crawler
=======================

Website crawling: frontier queue, robots compliance, sitemap parsing,
canonicalization, deduplication and rate-limited scheduling.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse

__all__ = ["CrawlJob", "CrawlStats", "RobotsRules", "Sitemap", "Crawler"]

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class CrawlJob:
    """A URL queued for crawling."""

    url: str
    priority: int = 5
    depth: int = 0
    added_at: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return {"url": self.url, "priority": self.priority, "depth": self.depth}


@dataclass
class CrawlStats:
    """Running crawl counters."""

    queued: int = 0
    fetched: int = 0
    failed: int = 0
    skipped: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {"queued": self.queued, "fetched": self.fetched, "failed": self.failed, "skipped": self.skipped}


class RobotsRules:
    """robots.txt compliance: allowed/disallowed path rules."""

    def __init__(self, raw: str = "") -> None:
        self.disallowed: List[str] = []
        self.allowed: List[str] = []
        self.parse(raw)

    def parse(self, raw: str) -> None:
        self.disallowed.clear()
        self.allowed.clear()
        in_group = False
        for line in (raw or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("user-agent:"):
                in_group = line.split(":", 1)[1].strip().lower() in ("*", "cie-os", "cieos")
                continue
            if not in_group:
                continue
            if line.lower().startswith("disallow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    self.disallowed.append(path)
            elif line.lower().startswith("allow:"):
                path = line.split(":", 1)[1].strip()
                if path:
                    self.allowed.append(path)

    def can_fetch(self, url: str) -> bool:
        path = urlparse(url).path or "/"
        longest = 0
        outcome = True
        for rule in self.allowed:
            if path.startswith(rule) and len(rule) > longest:
                longest = len(rule)
                outcome = True
        for rule in self.disallowed:
            if path.startswith(rule) and len(rule) > longest:
                longest = len(rule)
                outcome = False
        return outcome


class Sitemap:
    """Minimal XML sitemap parser."""

    def parse(self, raw: str) -> List[str]:
        urls: List[str] = []
        for match in re.finditer(r"<loc[^>]*>(.*?)</loc>", raw or "", re.IGNORECASE | re.DOTALL):
            url = match.group(1).strip()
            if url:
                urls.append(url)
        return urls


class Crawler:
    """Deterministic local crawler with frontier, robots and dedup."""

    def __init__(self, *, fetch_fn: Optional[Any] = None, delay_s: float = 0.0) -> None:
        self.fetch_fn = fetch_fn or (lambda url: "")
        self.delay_s = delay_s
        self.robots = RobotsRules()
        self.sitemap = Sitemap()
        self._frontier: List[CrawlJob] = []
        self._visited: Dict[str, str] = {}
        self._content_hashes: Dict[str, str] = {}
        self._last_fetch = 0.0
        self.stats = CrawlStats()

    def seed(self, urls: Sequence[str]) -> None:
        for url in urls:
            self._enqueue(url, priority=5, depth=0)

    def set_robots(self, raw: str) -> None:
        self.robots.parse(raw)

    def _enqueue(self, url: str, *, priority: int, depth: int) -> None:
        canonical = canonicalize(url)
        if canonical in self._visited:
            return
        if any(job.url == canonical for job in self._frontier):
            return
        self._frontier.append(CrawlJob(url=canonical, priority=priority, depth=depth))
        self.stats.queued += 1

    def next_job(self) -> Optional[CrawlJob]:
        if not self._frontier:
            return None
        now = time.time()
        if now - self._last_fetch < self.delay_s:
            return None
        self._frontier.sort(key=lambda job: (-job.priority, job.added_at))
        return self._frontier[0]

    def step(self) -> Optional[Dict[str, Any]]:
        """Fetch and process the next frontier job; returns page data."""
        job = self.next_job()
        if job is None:
            return None
        self._frontier.pop(0)
        if not self.robots.can_fetch(job.url):
            self.stats.skipped += 1
            return None
        self._last_fetch = time.time()
        try:
            content = self.fetch_fn(job.url)
        except Exception:  # noqa: BLE001 - failed fetches never halt the crawl
            self.stats.failed += 1
            return None
        digest = hashlib.sha256(content.encode("utf-8", "replace")).hexdigest()
        if digest in self._content_hashes:
            self.stats.skipped += 1
            return None
        self._content_hashes[digest] = job.url
        self._visited[job.url] = digest
        self.stats.fetched += 1
        return {"url": job.url, "content": content, "depth": job.depth}

    def run(self, max_pages: int = 50) -> List[Dict[str, Any]]:
        pages: List[Dict[str, Any]] = []
        while len(pages) < max(1, int(max_pages)):
            page = self.step()
            if page is None:
                break
            pages.append(page)
            for link in re.findall(r'<a[^>]*href\s*=\s*["\']([^"\']+)["\']', page["content"], re.IGNORECASE):
                if link.startswith(("http://", "https://")):
                    self._enqueue(link, priority=3, depth=page["depth"] + 1)
        return pages

    def visited(self) -> List[str]:
        return list(self._visited)

    def stats_dict(self) -> Dict[str, Any]:
        return self.stats.as_dict()


def canonicalize(url: str) -> str:
    """Normalize a URL: scheme+host lowercase, default ports stripped,
    fragment dropped, trailing slashes kept."""
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    host = (parsed.netloc or "").lower()
    if host.endswith(":80") and scheme == "http":
        host = host[:-3]
    if host.endswith(":443") and scheme == "https":
        host = host[:-4]
    return f"{scheme}://{host}{parsed.path or '/'}" + (("?" + parsed.query) if parsed.query else "")