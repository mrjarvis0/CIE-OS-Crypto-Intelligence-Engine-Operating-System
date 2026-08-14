"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.attribution.labels

Purpose:
    Entity label management.

    A key (address/entity id) may receive multiple label proposals from
    different heuristics; the store keeps the highest-confidence
    proposal while merging preserves first-registered labels.
"""

from __future__ import annotations

from typing import Any


class LabelStore:
    """
    Stores and queries labels for addresses and entities.
    """

    def __init__(self) -> None:
        self._labels: dict[str, dict[str, Any]] = {}

    def add(
        self,
        key: str,
        label: str,
        category: str = "unknown",
        confidence: float = 1.0,
    ) -> None:
        """
        Add a label for a key (address/entity id).

        When a label already exists for the key, the higher-confidence
        proposal wins so a strong verified label is never silently
        overwritten by a weaker heuristic.
        """
        existing = self._labels.get(key)
        if existing is None or confidence > existing.get("confidence", 0.0):
            self._labels[key] = {
                "label": label,
                "category": category,
                "confidence": confidence,
            }

    def get(self, key: str) -> dict[str, Any] | None:
        """
        Return the label for a key.
        """
        return self._labels.get(key)

    def all(self) -> dict[str, dict[str, Any]]:
        """
        Return all labels.
        """
        return dict(self._labels)

    def merge(self, other: "LabelStore") -> None:
        """
        Merge labels from another store.

        Existing keys keep their current value (first-registered wins).
        """
        for key, value in other.all().items():
            self._labels.setdefault(key, value)
