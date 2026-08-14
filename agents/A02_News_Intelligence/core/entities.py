"""
CIE-OS
A02 News Intelligence Agent

Module:
    core.entities

Purpose:
    Entity extraction — find stocks, crypto and forex mentions in text (Phase 1).

Design goals:
    - Rule-based only (no ML in Phase 1)
    - Only known symbols match — no arbitrary uppercase-word guessing
"""

from __future__ import annotations

import re

from .models import Entity
from .symbols import NAME_ALIASES, entity_type_for, name_for

# "$AAPL", "#BTC", "(NYSE: AAPL)", "(NASDAQ:AAPL)", "EUR/USD"
_SYMBOL_TAG_RE = re.compile(r"[$\u20bf#]\s*([A-Za-z0-9]{2,10})")
_PAIR_RE = re.compile(r"\b([A-Z]{3})\s*/\s*([A-Z]{3})\b")
_TICKER_RE = re.compile(r"(?<![A-Za-z])[A-Z]{2,5}(?![A-Za-z])")


def _find_aliases(text: str) -> list[Entity]:
    """Match known company/crypto names to symbols (case-insensitive, longest-first)."""

    found: dict[str, Entity] = {}
    lowered = text.lower()
    for name in sorted(NAME_ALIASES, key=len, reverse=True):
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])")
        for match in pattern.finditer(lowered):
            symbol = NAME_ALIASES[name]
            found.setdefault(
                symbol,
                Entity(
                    type=entity_type_for(symbol),  # type: ignore[arg-type]
                    symbol=symbol,
                    name=name_for(symbol),
                    context=_context(text, match.start(), match.end()),
                ),
            )
    return list(found.values())


def _context(text: str, start: int, end: int, radius: int = 60) -> str | None:
    """Snippet around a match for evidence/display."""

    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    return text[lo:hi].strip()


def extract_entities(item_text: str) -> list[Entity]:
    """Extract all known financial entities from text (no duplicates)."""

    if not item_text:
        return []

    found: dict[str, Entity] = {}

    # $BTC / #ETH / $AAPL tags
    for match in _SYMBOL_TAG_RE.finditer(item_text):
        symbol = match.group(1).upper()
        etype = entity_type_for(symbol)
        if not etype:
            continue
        found[symbol] = Entity(
            type=etype,  # type: ignore[arg-type]
            symbol=symbol,
            name=name_for(symbol),
            context=_context(item_text, match.start(), match.end()),
        )

    # EUR/USD forex pairs
    for match in _PAIR_RE.finditer(item_text):
        symbol = (match.group(1) + match.group(2)).upper()
        etype = entity_type_for(symbol)
        if not etype:
            continue
        found[symbol] = Entity(
            type=etype,  # type: ignore[arg-type]
            symbol=symbol,
            name=name_for(symbol),
            context=_context(item_text, match.start(), match.end()),
        )

    # Bare uppercase symbols (only if they are known symbols)
    for match in _TICKER_RE.finditer(item_text):
        symbol = match.group(0)
        etype = entity_type_for(symbol)
        if not etype:
            continue
        found[symbol] = Entity(
            type=etype,  # type: ignore[arg-type]
            symbol=symbol,
            name=name_for(symbol),
            context=_context(item_text, match.start(), match.end()),
        )

    # Company/crypto names
    for entity in _find_aliases(item_text):
        found.setdefault(entity.symbol, entity)

    return list(found.values())


__all__ = ["extract_entities"]
