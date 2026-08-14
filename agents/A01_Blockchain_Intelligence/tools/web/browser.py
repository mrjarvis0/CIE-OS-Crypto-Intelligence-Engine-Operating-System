"""
Tools :: Web :: Browser
=======================

Browser session management: cookies, headers, history, navigation and
user-agent handling. Deterministic local session store stands in for a
real browser; automation backends subclass ``BrowserBackend``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..utils.helpers import iso_now
from .crawler import canonicalize
from .parser import ParsedPage
from .scraper import Scraper

__all__ = ["Cookie", "PageSnapshot", "BrowserSession", "Browser"]


@dataclass
class Cookie:
    """An HTTP cookie."""

    name: str
    value: str
    domain: str = ""
    path: str = "/"
    secure: bool = False
    expires_at: float = 0.0

    def expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": self.value, "domain": self.domain, "path": self.path, "secure": self.secure}


@dataclass
class PageSnapshot:
    """What the browser sees on a page."""

    url: str
    title: str = ""
    text: str = ""
    html: str = ""
    visited_at: str = field(default_factory=iso_now)

    def as_dict(self) -> Dict[str, Any]:
        return {"url": self.url, "title": self.title, "text": self.text, "visited_at": self.visited_at}


class BrowserSession:
    """Session state: cookies, headers, history and current page."""

    def __init__(self, user_agent: str = "cie-os-browser/1.0") -> None:
        self.user_agent = user_agent
        self.cookies: List[Cookie] = []
        self.headers: Dict[str, str] = {"User-Agent": user_agent}
        self.history: List[PageSnapshot] = []
        self.current: Optional[PageSnapshot] = None

    def set_cookie(self, cookie: Cookie) -> None:
        self.cookies = [c for c in self.cookies if not (c.name == cookie.name and c.domain == cookie.domain)]
        if not cookie.expired():
            self.cookies.append(cookie)

    def cookie_header(self, domain: str = "") -> str:
        fresh = [c for c in self.cookies if not c.expired()]
        relevant = [c for c in fresh if not domain or domain.endswith(c.domain) if c.domain]
        if not relevant:
            relevant = fresh
        return "; ".join(f"{c.name}={c.value}" for c in relevant)

    def set_header(self, name: str, value: str) -> None:
        self.headers[name] = value

    def push_snapshot(self, snapshot: PageSnapshot) -> None:
        self.history.append(snapshot)
        self.current = snapshot

    def as_dict(self) -> Dict[str, Any]:
        return {
            "user_agent": self.user_agent,
            "cookies": [c.as_dict() for c in self.cookies],
            "headers": dict(self.headers),
            "history": [s.as_dict() for s in self.history[-20:]],
            "current": self.current.as_dict() if self.current else None,
        }


class Browser:
    """Deterministic browser facade over the scraper and session."""

    def __init__(self, *, store: Optional[Mapping[str, str]] = None, user_agent: str = "cie-os-browser/1.0") -> None:
        self.session = BrowserSession(user_agent=user_agent)
        self.scraper = Scraper(store=store, user_agent=user_agent)

    def navigate(self, url: str) -> PageSnapshot:
        result = self.scraper.scrape(url)
        if not result.ok or result.page is None:
            raise FileNotFoundError(result.error or f"cannot navigate to {url!r}")
        page = result.page
        snapshot = PageSnapshot(url=page.url, title=page.title, text=page.text[:5000], html=page.markdown[:5000])
        self.session.push_snapshot(snapshot)
        return snapshot

    def back(self) -> Optional[PageSnapshot]:
        if len(self.session.history) < 2:
            return None
        self.session.history.pop()
        self.session.current = self.session.history[-1] if self.session.history else None
        return self.session.current

    def snapshot(self) -> Optional[PageSnapshot]:
        return self.session.current