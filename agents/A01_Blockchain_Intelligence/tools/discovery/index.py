"""
Tools :: Discovery :: Index
===========================

Optimized inverted indexes over the catalog.

Supported indexes: name (tokenized), tag, capability, namespace, category
and version. Indexes are maintained incrementally via ``add``/``remove``
and support fast postings lookup plus prefix matching.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Set

from .catalog import DiscoveryEntry

__all__ = ["DiscoveryIndex", "tokenize"]

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(value: str) -> List[str]:
    """Lower-case alphanumeric tokens of a string."""
    return _TOKEN_RE.findall(value.lower())


class DiscoveryIndex:
    """Incremental inverted index for one or more fields."""

    _FIELDS = ("name", "tag", "capability", "namespace", "category", "version")

    def __init__(self) -> None:
        self._postings: Dict[str, Dict[str, Set[str]]] = {
            field: {} for field in self._FIELDS
        }
        self._names: Dict[str, str] = {}

    # -- maintenance ----------------------------------------------------------- #

    def add(self, entry: DiscoveryEntry) -> None:
        """Index a (new or updated) entry; previous postings are replaced."""
        self.remove(entry.tool_id)
        self._names[entry.tool_id] = entry.name
        self._add_field("name", tokenize(entry.name), entry.tool_id)
        self._add_field("tag", [t.lower() for t in entry.tags], entry.tool_id)
        self._add_field("capability", [c.lower() for c in entry.capabilities], entry.tool_id)
        self._add_field("namespace", [entry.namespace.lower()], entry.tool_id)
        self._add_field("category", [entry.category.lower()], entry.tool_id)
        self._add_field("version", [entry.version.lower()], entry.tool_id)

    def _add_field(self, field: str, terms: Iterable[str], tool_id: str) -> None:
        postings = self._postings[field]
        for term in terms:
            if not term:
                continue
            postings.setdefault(term, set()).add(tool_id)

    def remove(self, tool_id: str) -> None:
        name = self._names.pop(tool_id, None)
        for field, postings in self._postings.items():
            for term in list(postings):
                ids = postings[term]
                ids.discard(tool_id)
                if not ids:
                    del postings[term]

    def rebuild(self, entries: Iterable[DiscoveryEntry]) -> None:
        for field in self._postings:
            self._postings[field].clear()
        self._names.clear()
        for entry in entries:
            self.add(entry)

    # -- queries --------------------------------------------------------------- #

    def postings(self, field: str, term: str) -> Set[str]:
        """Tool ids posting to an exact term in a field (term lower-cased)."""
        return set(self._postings.get(field, {}).get(term.lower(), set()))

    def prefix(self, field: str, prefix: str) -> Set[str]:
        """Tool ids whose term in a field starts with ``prefix``."""
        prefix = prefix.lower()
        postings = self._postings.get(field, {})
        result: Set[str] = set()
        for term, ids in postings.items():
            if term.startswith(prefix):
                result |= ids
        return result

    def names(self) -> Dict[str, str]:
        return dict(self._names)

    def stats(self) -> Dict[str, int]:
        return {field: len(postings) for field, postings in self._postings.items()}