"""
Tools :: Web :: Parser
======================

HTML, Markdown, JSON, XML and RSS parsing plus metadata and structured
data extraction. Pure-stdlib: no third-party parsing dependencies.
"""

from __future__ import annotations

import html as _html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlparse

__all__ = [
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
]

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class ParseResult:
    """Generic parse outcome."""

    ok: bool
    data: Any = None
    error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "error": self.error}


@dataclass
class ParsedPage:
    """A parsed web page with normalized content."""

    url: str = ""
    title: str = ""
    text: str = ""
    markdown: str = ""
    meta: Dict[str, str] = field(default_factory=dict)
    links: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    structured: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "markdown": self.markdown,
            "meta": dict(self.meta),
            "links": list(self.links),
            "images": list(self.images),
            "structured": list(self.structured),
        }


def strip_tags(raw: str) -> str:
    cleaned = _SCRIPT_STYLE_RE.sub(" ", raw or "")
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = _html.unescape(cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def extract_title(raw: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", raw or "", re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _WHITESPACE_RE.sub(" ", _html.unescape(match.group(1))).strip()


def extract_meta(raw: str) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    for match in re.finditer(r"<meta[^>]*>", raw or "", re.IGNORECASE):
        tag = match.group(0)
        name = re.search(r'(?:name|property|http-equiv)\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
        content = re.search(r'content\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
        if name and content:
            key = name.group(1).strip().lower()
            value = _html.unescape(content.group(1)).strip()
            if key and value and key not in meta:
                meta[key] = value
    return meta


def extract_links(raw: str, base_url: str = "") -> List[str]:
    links: List[str] = []
    for match in re.finditer(r'<a[^>]*href\s*=\s*["\']([^"\']+)["\']', raw or "", re.IGNORECASE):
        href = _html.unescape(match.group(1)).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if base_url:
            href = urljoin(base_url, href)
        links.append(href)
    return links


def extract_text(raw: str) -> str:
    return strip_tags(raw)


def markdown_from_html(raw: str) -> str:
    """Best-effort HTML -> Markdown conversion (headings, links, lists)."""
    text = raw or ""
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    for level in range(6, 0, -1):
        text = re.sub(rf"<h{level}[^>]*>(.*?)</h{level}>", lambda m: "\n" + "#" * level + " " + strip_tags(m.group(1)) + "\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: "\n- " + strip_tags(m.group(1)), text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<b(?=[\s>])[^>]*>(.*?)</b>", lambda m: "**" + strip_tags(m.group(1)) + "**", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<strong[^>]*>(.*?)</strong>", lambda m: "**" + strip_tags(m.group(1)) + "**", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<i(?=[\s>])[^>]*>(.*?)</i>", lambda m: "*" + strip_tags(m.group(1)) + "*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<a[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", lambda m: f"[{strip_tags(m.group(2))}]({m.group(1)})", text, flags=re.IGNORECASE | re.DOTALL)
    return _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def parse_json(raw: str) -> ParseResult:
    try:
        return ParseResult(ok=True, data=json.loads(raw))
    except (ValueError, TypeError) as exc:
        return ParseResult(ok=False, error=f"JSON parse failed: {exc}")


def parse_xml(raw: str) -> ParseResult:
    try:
        root = ET.fromstring(raw)
        return ParseResult(ok=True, data=root)
    except ET.ParseError as exc:
        return ParseResult(ok=False, error=f"XML parse failed: {exc}")


def parse_structured_data(raw: str, base_url: str = "") -> List[Dict[str, Any]]:
    """Extract lightweight structured records (JSON-LD script blocks)."""
    records: List[Dict[str, Any]] = []
    for match in re.finditer(r'<script[^>]*type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>', raw or "", re.IGNORECASE | re.DOTALL):
        parsed = parse_json(match.group(1).strip())
        if not parsed.ok:
            continue
        value = parsed.data
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            records.append(value)
    return records


class WebParser:
    """Facade combining all parsing primitives into page objects."""

    def parse_page(self, html_raw: str, url: str = "") -> ParsedPage:
        title = extract_title(html_raw)
        meta = extract_meta(html_raw)
        if not title:
            title = meta.get("og:title", meta.get("twitter:title", ""))
        return ParsedPage(
            url=url,
            title=title,
            text=extract_text(html_raw),
            markdown=markdown_from_html(html_raw),
            meta=meta,
            links=extract_links(html_raw, url),
            images=[urljoin(url, src) for src in re.findall(r'<img[^>]*src\s*=\s*["\']([^"\']+)["\']', html_raw, re.IGNORECASE) if url],
            structured=parse_structured_data(html_raw, url),
        )