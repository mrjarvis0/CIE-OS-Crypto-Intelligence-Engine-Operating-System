"""
CIE-OS
A02 News Intelligence Agent

Module:
    intelligence.claims

Purpose:
    Rule-based claim extraction from news items (Phase 2).

    Example:
        "SEC will approve XYZ ETF tomorrow."
        -> claim_text="SEC will approve XYZ ETF tomorrow."
        -> entities=["XYZ"], time_hint="tomorrow"
"""

from __future__ import annotations

import re

from pydantic import BaseModel

# ==============================================================================
# MODELS
# ==============================================================================


class Claim(BaseModel):
    """A single extractable claim."""

    claim_text: str
    entities: list[str] = []
    time_hint: str | None = None


# ==============================================================================
# TEXT HELPERS
# ==============================================================================

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TIME_HINT_RE = re.compile(
    r"\b(today|tonight|tomorrow|next week|this week|next month|"
    r"by (?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|january|february|march|april|may|june|july|august|september|"
    r"october|november|december))\b",
    re.IGNORECASE,
)
_MAX_CLAIM_CHARS = 250


def split_sentences(text: str) -> list[str]:
    """Split text into sentences (crude but dependency-free)."""

    parts = [p.strip() for p in _SENTENCE_RE.split(text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def extract_time_hint(text: str) -> str | None:
    """Return a time hint (tomorrow, next week...) if present."""

    match = _TIME_HINT_RE.search(text)
    return match.group(0).lower() if match else None


def _score_sentence(sentence: str, entity_symbols: set[str]) -> float:
    """Prefer sentences that mention entities and are informative."""

    score = 0.0
    words = sentence.split()
    entity_hits = sum(1 for symbol in entity_symbols if symbol in sentence)
    score += 2.0 * entity_hits
    score += 0.5 if len(words) >= 6 else 0.0
    score += 0.5 if any(c.isupper() for c in sentence[1:5]) else 0.0
    return score


def extract_claim(title: str, content: str, entity_symbols: list[str]) -> Claim:
    """Extract the most likely claim from title + content."""

    entity_set = {s.upper() for s in entity_symbols}
    sentences = split_sentences(title) + split_sentences(content)
    sentences = list(dict.fromkeys(sentences))  # dedupe, keep order
    if not sentences:
        text = f"{title} {content}".strip()
        return Claim(claim_text=text[:_MAX_CLAIM_CHARS], entities=entity_symbols)

    best = max(sentences, key=lambda s: _score_sentence(s, entity_set))
    return Claim(
        claim_text=best[:_MAX_CLAIM_CHARS],
        entities=entity_symbols,
        time_hint=extract_time_hint(" ".join(sentences)),
    )


__all__ = ["Claim", "split_sentences", "extract_time_hint", "extract_claim"]
