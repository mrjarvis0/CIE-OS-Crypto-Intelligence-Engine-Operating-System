"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.dedup

Purpose:
    Fingerprinting and duplicate detection for incoming items (Phase 1).

Design goals:
    - Pure functions, no I/O
    - Source-level dedup: 10 articles copying 1 tweet collapse to 1 story
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_STRIP_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def fingerprint(text: str) -> str:
    """Canonical sha256 of normalized text."""

    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower()
    text = _STRIP_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def title_fingerprint(title: str) -> str:
    """Fingerprint for a headline."""

    return fingerprint(title)


def content_fingerprint(content: str) -> str:
    """Fingerprint for full article text (truncated to 800 chars)."""

    return fingerprint((content or "")[:800])


def looks_duplicate(
    url: str | None,
    title_fp: str,
    content_fp: str,
    seen_urls: set[str],
    seen_title_fps: set[str],
    seen_content_fps: set[str],
) -> bool:
    """In-memory duplicate check against previously seen fingerprints."""

    if url and url in seen_urls:
        return True
    if title_fp and title_fp in seen_title_fps:
        return True
    if content_fp and content_fp in seen_content_fps:
        return True
    return False


def note_seen(
    url: str | None,
    title_fp: str,
    content_fp: str,
    seen_urls: set[str],
    seen_title_fps: set[str],
    seen_content_fps: set[str],
) -> None:
    """Register fingerprints as seen (mutates the given sets)."""

    if url:
        seen_urls.add(url)
    if title_fp:
        seen_title_fps.add(title_fp)
    if content_fp:
        seen_content_fps.add(content_fp)


__all__ = [
    "fingerprint",
    "title_fingerprint",
    "content_fingerprint",
    "looks_duplicate",
    "note_seen",
]
