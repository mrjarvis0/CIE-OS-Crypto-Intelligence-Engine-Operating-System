"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.normalize

Purpose:
    Text cleaning, timestamp parsing, language guessing (Phase 1).

Design goals:
    - Pure functions, no I/O
    - No external dependencies
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

from .models import NormalizedItem, RawItem
from .dedup import content_fingerprint, title_fingerprint

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_JUNK_RE = re.compile(
    r"(?i)\b(sign up|subscribe|click here|read more|advertisement|"
    r"all rights reserved|follow us on|terms of service|privacy policy)\b"
)


def strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""

    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    return text


def clean_text(text: str) -> str:
    """Full cleaning pipeline for article text."""

    text = strip_html(text)
    text = _CTRL_RE.sub("", text)
    text = _JUNK_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning None on failure."""

    if not value:
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def guess_language(text: str) -> str:
    """Tiny script-based language guess (no external deps)."""

    sample = text.strip()[:400]
    if not sample:
        return "unknown"

    scores = {
        "devanagari": len(re.findall(r"[\u0900-\u097f]", sample)),
        "cjk": len(re.findall(r"[\u4e00-\u9fff]", sample)),
        "arabic": len(re.findall(r"[\u0600-\u06ff]", sample)),
        "cyrillic": len(re.findall(r"[\u0400-\u04ff]", sample)),
        "latin": len(re.findall(r"[a-zA-Z]", sample)),
    }
    for script, count in scores.items():
        if script != "latin" and count > 10:
            if script == "devanagari":
                return "hi"
            if script == "cjk":
                return "zh"
            if script == "arabic":
                return "ar"
            return "other"
    return "en"


def normalize_item(raw: RawItem) -> NormalizedItem:
    """Convert a RawItem into a cleaned, fingerprinted NormalizedItem."""

    title = clean_text(raw.title)
    content = clean_text(raw.content)
    title_fp = title_fingerprint(title) if title else ""
    content_fp = content_fingerprint(content) if content else ""

    return NormalizedItem(
        source=raw.source,
        source_key=raw.source_key,
        url=raw.url,
        title=title,
        content=content,
        author=(raw.author or "").strip() or None,
        published_at=raw.published_at,
        fetched_at=raw.fetched_at,
        language=guess_language(f"{title} {content}"),
        platform=raw.platform,
        title_fingerprint=title_fp,
        content_fingerprint=content_fp,
    )


def raw_published_at(raw: RawItem) -> datetime | None:
    """Return UTC-normalized published_at for a RawItem."""

    value = raw.published_at
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


__all__ = [
    "strip_html",
    "clean_text",
    "parse_timestamp",
    "guess_language",
    "normalize_item",
    "raw_published_at",
]
