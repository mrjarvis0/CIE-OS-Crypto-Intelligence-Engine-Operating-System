"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.correlation.correlator

Purpose:
    Central correlation orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Correlation:
    """
    A detected relationship between two subjects.
    """

    left: str
    right: str
    relation: str
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left,
            "right": self.right,
            "relation": self.relation,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
        }


class Correlator:
    """
    Aggregates correlations from registered linkers.
    """

    def __init__(self) -> None:
        self._linkers: list[Any] = []
        self._correlations: list[Correlation] = []

    def add_linker(self, linker: Any) -> "Correlator":
        """
        Register a linker exposing a `link` method.
        """
        self._linkers.append(linker)
        return self

    def correlate(self, subjects: list[dict[str, Any]]) -> list[Correlation]:
        """
        Run all linkers over the subjects and collect correlations.
        """
        self._correlations.clear()
        for linker in self._linkers:
            link_fn = getattr(linker, "link", None)
            if link_fn is None:
                continue
            for result in link_fn(subjects):
                if isinstance(result, Correlation):
                    self._correlations.append(result)
        return list(self._correlations)

    @property
    def results(self) -> list[Correlation]:
        """Latest correlations."""
        return list(self._correlations)
